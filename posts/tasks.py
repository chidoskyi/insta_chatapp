from celery import shared_task
from django.core.files.base import ContentFile
from PIL import Image, ImageDraw, ImageFont
import io
import subprocess
import os
import json
from .models import PostMedia


@shared_task
def generate_thumbnail(media_id):
    """Generate thumbnail for image media"""
    try:
        media = PostMedia.objects.get(id=media_id)
        if media.media_type != 'image' or not media.file:
            return f"Skipped: {media_id} (not an image or no file)"
        
        # Open image
        image = Image.open(media.file.path)
        
        # Get image dimensions
        media.width, media.height = image.size
        
        # Create thumbnail (max 300x300)
        thumbnail_size = (300, 300)
        image.thumbnail(thumbnail_size, Image.Resampling.LANCZOS)
        
        # Save thumbnail
        thumb_io = io.BytesIO()
        image_format = image.format or 'JPEG'
        image.save(thumb_io, format=image_format, quality=85)
        thumb_io.seek(0)
        
        # Save to model
        filename = f"thumb_{media.file.name.split('/')[-1]}"
        media.thumbnail.save(filename, ContentFile(thumb_io.read()), save=False)
        media.save()
        
        return f"Thumbnail generated for media {media_id}"
        
    except PostMedia.DoesNotExist:
        return f"Media {media_id} not found"
    except Exception as e:
        return f"Error generating thumbnail for {media_id}: {str(e)}"


@shared_task
def process_video_metadata(media_id):
    """Extract video metadata (duration, dimensions) using FFmpeg"""
    try:
        media = PostMedia.objects.get(id=media_id)
        if media.media_type != 'video' or not media.file:
            return f"Skipped: {media_id} (not a video or no file)"
        
        video_path = media.file.path
        
        # Use FFprobe to get video metadata
        ffprobe_cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            video_path
        ]
        
        result = subprocess.run(
            ffprobe_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            return f"FFprobe error for {media_id}: {result.stderr}"
        
        metadata = json.loads(result.stdout)
        
        # Extract video stream info
        video_stream = next(
            (s for s in metadata.get('streams', []) if s.get('codec_type') == 'video'),
            None
        )
        
        if video_stream:
            media.width = video_stream.get('width')
            media.height = video_stream.get('height')
        
        # Extract duration
        format_info = metadata.get('format', {})
        duration = format_info.get('duration')
        if duration:
            media.duration = float(duration)
        
        media.save()
        
        # Generate video thumbnail
        generate_video_thumbnail.delay(media_id)
        
        return f"Video metadata processed for {media_id}"
        
    except PostMedia.DoesNotExist:
        return f"Media {media_id} not found"
    except subprocess.TimeoutExpired:
        return f"Timeout processing video {media_id}"
    except Exception as e:
        return f"Error processing video {media_id}: {str(e)}"


@shared_task
def generate_video_thumbnail(media_id):
    """Generate thumbnail for video using FFmpeg"""
    try:
        media = PostMedia.objects.get(id=media_id)
        if media.media_type != 'video' or not media.file:
            return f"Skipped: {media_id} (not a video or no file)"
        
        video_path = media.file.path
        
        # Create temporary thumbnail path
        thumb_filename = f"thumb_{os.path.splitext(os.path.basename(video_path))[0]}.jpg"
        temp_thumb_path = os.path.join('/tmp', thumb_filename)
        
        # Extract frame at 1 second (or 10% of duration if shorter)
        seek_time = '00:00:01'
        if media.duration and media.duration < 10:
            seek_time = f'00:00:00.{int(media.duration * 100):03d}'
        
        # Use FFmpeg to extract a frame
        ffmpeg_cmd = [
            'ffmpeg',
            '-i', video_path,
            '-ss', seek_time,
            '-vframes', '1',
            '-vf', 'scale=300:300:force_original_aspect_ratio=decrease',
            '-q:v', '2',
            '-y',  # Overwrite output file
            temp_thumb_path
        ]
        
        result = subprocess.run(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30
        )
        
        if result.returncode != 0:
            return f"FFmpeg error for {media_id}: {result.stderr.decode()}"
        
        # Save thumbnail to model
        with open(temp_thumb_path, 'rb') as f:
            media.thumbnail.save(thumb_filename, ContentFile(f.read()), save=True)
        
        # Clean up temp file
        if os.path.exists(temp_thumb_path):
            os.remove(temp_thumb_path)
        
        return f"Video thumbnail generated for {media_id}"
        
    except PostMedia.DoesNotExist:
        return f"Media {media_id} not found"
    except subprocess.TimeoutExpired:
        return f"Timeout generating thumbnail for {media_id}"
    except Exception as e:
        return f"Error generating video thumbnail for {media_id}: {str(e)}"


def is_dark_color(hex_color):
    """Determine if a color is dark (for text color contrast)"""
    hex_color = hex_color.lstrip('#')
    r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    # Calculate perceived brightness
    brightness = (r * 299 + g * 587 + b * 114) / 1000
    return brightness < 128


@shared_task
def generate_text_slide_image(media_id):
    """Generate an image for text-only slide"""
    try:
        media = PostMedia.objects.get(id=media_id)
        if media.media_type != 'text' or not media.text_content:
            return f"Skipped: {media_id} (not a text slide)"
        
        # Create image with text
        width, height = 1080, 1080  # Instagram square size
        
        # Create gradient background
        background_color = media.background_color or '#4A90E2'
        img = Image.new('RGB', (width, height), color=background_color)
        draw = ImageDraw.Draw(img)
        
        # Try to use a nice font, fallback to default
        try:
            # Try to load a system font
            font_size = 48
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except:
            try:
                # Fallback for macOS
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 48)
            except:
                try:
                    # Fallback for Windows
                    font = ImageFont.truetype("arial.ttf", 48)
                except:
                    # Use default font
                    font = ImageFont.load_default()
        
        # Wrap text
        text = media.text_content
        max_width = width - 120  # padding
        
        # Simple text wrapping
        lines = []
        words = text.split()
        current_line = []
        
        for word in words:
            test_line = ' '.join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
        
        if current_line:
            lines.append(' '.join(current_line))
        
        # Calculate total text height
        total_height = sum([draw.textbbox((0, 0), line, font=font)[3] - 
                           draw.textbbox((0, 0), line, font=font)[1] + 10 
                           for line in lines])
        
        # Center text vertically
        y = (height - total_height) // 2
        
        # Draw text
        text_color = '#ffffff' if is_dark_color(background_color) else '#000000'
        
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            x = (width - text_width) // 2
            draw.text((x, y), line, fill=text_color, font=font)
            y += bbox[3] - bbox[1] + 10
        
        # Save image
        img_io = io.BytesIO()
        img.save(img_io, format='PNG', quality=95)
        img_io.seek(0)
        
        filename = f"text_slide_{media.id}.png"
        media.file.save(filename, ContentFile(img_io.read()), save=False)
        
        # Generate thumbnail
        media.width = width
        media.height = height
        
        # Create thumbnail
        thumb_img = img.copy()
        thumb_img.thumbnail((300, 300), Image.Resampling.LANCZOS)
        thumb_io = io.BytesIO()
        thumb_img.save(thumb_io, format='PNG', quality=85)
        thumb_io.seek(0)
        
        thumb_filename = f"thumb_text_slide_{media.id}.png"
        media.thumbnail.save(thumb_filename, ContentFile(thumb_io.read()), save=False)
        media.save()
        
        return f"Text slide image generated for {media_id}"
        
    except PostMedia.DoesNotExist:
        return f"Media {media_id} not found"
    except Exception as e:
        return f"Error generating text slide: {str(e)}"


@shared_task
def cleanup_old_media():
    """Clean up media files for deleted posts (run periodically)"""
    from django.core.files.storage import default_storage
    
    try:
        # Find PostMedia records without associated posts
        orphaned_media = PostMedia.objects.filter(post__isnull=True)
        
        deleted_count = 0
        for media in orphaned_media:
            # Delete files from storage
            if media.file:
                if default_storage.exists(media.file.name):
                    default_storage.delete(media.file.name)
            
            if media.thumbnail:
                if default_storage.exists(media.thumbnail.name):
                    default_storage.delete(media.thumbnail.name)
            
            media.delete()
            deleted_count += 1
        
        return f"Cleaned up {deleted_count} orphaned media files"
        
    except Exception as e:
        return f"Error during cleanup: {str(e)}"


@shared_task
def process_post_media(post_id):
    """Process all media for a post (orchestrator task)"""
    try:
        from .models import Post
        post = Post.objects.get(id=post_id)
        
        for media in post.media.all():
            if media.media_type == 'image':
                generate_thumbnail.delay(media.id)
            elif media.media_type == 'video':
                process_video_metadata.delay(media.id)
            elif media.media_type == 'text':
                generate_text_slide_image.delay(media.id)
        
        return f"Processing initiated for all media in post {post_id}"
        
    except Exception as e:
        return f"Error processing post media: {str(e)}"