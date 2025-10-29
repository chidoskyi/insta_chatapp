from celery import shared_task
from django.core.files.base import ContentFile
from PIL import Image
import io


@shared_task
def process_reel_video(reel_id):
    """Process reel video: extract thumbnail, get duration and dimensions"""
    from .models import Reel
    
    try:
        reel = Reel.objects.get(id=reel_id)
        
        if not reel.video:
            return f"Reel {reel_id} has no video"
        
        # In production, use FFmpeg to:
        # 1. Extract first frame as thumbnail
        # 2. Get video dimensions
        # 3. Get video duration
        # 4. Optionally: compress/transcode video
        
        # Placeholder implementation
        # Install moviepy: pip install moviepy
        # Or use FFmpeg directly: pip install ffmpeg-python
        
        # Example with moviepy (uncomment if installed):
        # from moviepy.editor import VideoFileClip
        # 
        # clip = VideoFileClip(reel.video.path)
        # 
        # # Get dimensions and duration
        # reel.width = clip.w
        # reel.height = clip.h
        # reel.duration = clip.duration
        # 
        # # Extract first frame as thumbnail
        # frame = clip.get_frame(0)
        # thumb_img = Image.fromarray(frame)
        # thumb_img.thumbnail((300, 300), Image.Resampling.LANCZOS)
        # 
        # thumb_io = io.BytesIO()
        # thumb_img.save(thumb_io, format='JPEG', quality=85)
        # thumb_io.seek(0)
        # 
        # filename = f"thumb_{reel.id}.jpg"
        # reel.thumbnail.save(filename, ContentFile(thumb_io.read()), save=False)
        # 
        # clip.close()
        # reel.save()
        
        # For now, just mark as processed
        reel.save()
        
        return f"Processed reel {reel_id}"
    
    except Exception as e:
        return f"Error processing reel {reel_id}: {str(e)}"


@shared_task
def cleanup_deleted_reels():
    """Permanently delete soft-deleted reels older than 30 days"""
    from .models import Reel
    from django.utils import timezone
    from datetime import timedelta
    
    cutoff_date = timezone.now() - timedelta(days=30)
    
    deleted_reels = Reel.objects.filter(
        is_deleted=True,
        updated_at__lt=cutoff_date
    )
    
    count = 0
    for reel in deleted_reels:
        # Delete video files
        if reel.video:
            try:
                if os.path.isfile(reel.video.path):
                    os.remove(reel.video.path)
            except:
                pass
        
        if reel.thumbnail:
            try:
                if os.path.isfile(reel.thumbnail.path):
                    os.remove(reel.thumbnail.path)
            except:
                pass
        
        reel.delete()
        count += 1
    
    return f"Permanently deleted {count} old reels"