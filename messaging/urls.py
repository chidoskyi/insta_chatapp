from django.urls import path
from . import views

app_name = 'messaging'

urlpatterns = [
    # ============ CONVERSATIONS ============
    path('conversations/', views.ConversationListCreateView.as_view(), name='conversation_list_create'),
    path('conversations/<uuid:pk>/', views.ConversationDetailView.as_view(), name='conversation_detail'),
    path('conversations/<uuid:conversation_id>/messages/', views.ConversationMessagesView.as_view(), name='conversation_messages'),
    path('conversations/<uuid:conversation_id>/read/', views.MarkConversationReadView.as_view(), name='mark_conversation_read'),
    
    
    # ============ MESSAGES ============
    path('messages/<uuid:pk>/', views.MessageDetailView.as_view(), name='message_detail'),
    path('messages/<uuid:message_id>/forward/', views.ForwardMessageView.as_view(), name='forward_message'),
    path('messages/<uuid:message_id>/react/', views.MessageReactionView.as_view(), name='message_reaction'),
    path('messages/<uuid:message_id>/star/', views.StarMessageView.as_view(), name='star_message'),
    path('messages/starred/', views.StarredMessagesListView.as_view(), name='starred_messages'),
    path('messages/search/', views.search_messages, name='search_messages'),
    
    # ============ GROUP INVITE LINKS ============
    path('conversations/<uuid:conversation_id>/invite/create/', views.CreateGroupInviteLinkView.as_view(), name='create_invite_link'),
    path('conversations/<uuid:conversation_id>/invite/<uuid:link_id>/revoke/', views.RevokeGroupInviteLinkView.as_view(), name='revoke_invite_link'),
    path('invite/<str:invite_code>/join/', views.JoinGroupViaInviteView.as_view(), name='join_via_invite'),
    # ============ GROUP MANAGEMENT ============
    path('conversations/<uuid:conversation_id>/members/add/', views.AddMemberView.as_view(), name='add_member'),
    path('conversations/<uuid:conversation_id>/members/remove/', views.RemoveMemberView.as_view(), name='remove_member'),
    path('conversations/<uuid:conversation_id>/members/promote/', views.PromoteMemberView.as_view(), name='promote_member'),
    path('conversations/<uuid:conversation_id>/members/demote/', views.DemoteMemberView.as_view(), name='demote_member'),
    
    # ============ STATS ============
    path('conversations/unread-count/', views.unread_conversations_count, name='unread_count'),
    
    # ============ CONVERSATION ACTIONS ============
    path('conversations/<uuid:conversation_id>/pin/', views.PinConversationView.as_view(), name='pin_conversation'),
    path('conversations/<uuid:conversation_id>/archive/', views.ArchiveConversationView.as_view(), name='archive_conversation'),
    path('conversations/<uuid:conversation_id>/mute/', views.MuteConversationView.as_view(), name='mute_conversation'),
    
    # ============ BLOCKING ============
    path('block/', views.BlockUserView.as_view(), name='block_user'),
    path('unblock/', views.UnblockUserView.as_view(), name='unblock_user'),
    path('blocked/', views.BlockedUsersListView.as_view(), name='blocked_users'),
    

        # ============ CALLS ============
    path('calls/initiate/', views.InitiateCallView.as_view(), name='initiate_call'),
    path('calls/<uuid:pk>/', views.CallDetailView.as_view(), name='call_detail'),
    path('calls/<uuid:call_id>/answer/', views.AnswerCallView.as_view(), name='answer_call'),
    path('calls/<uuid:call_id>/end/', views.EndCallView.as_view(), name='end_call'),
    path('calls/history/<uuid:conversation_id>/', views.CallHistoryView.as_view(), name='call_history'),
    path('calls/my-calls/', views.my_calls, name='my_calls'),
    path('turn-credentials/', views.TurnCredentialsView.as_view(), name='turn_credentials'),
]






