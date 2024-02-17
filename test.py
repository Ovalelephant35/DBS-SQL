import gi
gi.require_version('Gtk', '3.0')
gi.require_version('TelepathyGLib', '0.12')

from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import TelepathyGLib
from gi.repository import GLib

gi.require_version('Gst', '1.0')
from gi.repository import Gst

OSK_HEIGHT = [400, 300]
SLASH = '-x-SLASH-x-'  # slash safe encoding

import logging
import json
import os
import time
import dbus
from gettext import gettext as _

from sugar3.graphics import style
from sugar3.graphics.icon import EventIcon, Icon
from sugar3.graphics.alert import NotifyAlert
from sugar3.graphics.toolbarbox import ToolbarBox
from sugar3.graphics.toolbutton import ToolButton
from sugar3.activity import activity
from sugar3.activity.activity import get_bundle_path
from sugar3.presence import presenceservice
from sugar3.activity.widgets import ActivityToolbarButton
from sugar3.activity.widgets import StopButton
from sugar3.activity.activity import get_activity_root
from sugar3.activity.activity import show_object_in_journal
from sugar3.datastore import datastore
from sugar3 import profile
from sugar3.graphics import iconentry

from chat import smilies
from chat.box import ChatBox

logger = logging.getLogger('chat-activity')

Gst.init([])

class Chat(activity.Activity):

    def __init__(self, handle):
        pservice = presenceservice.get_instance()
        self.owner = pservice.get_owner()

        self.chatbox = ChatBox(self.owner)
        self.chatbox.connect('open-on-journal', self.__open_on_journal)
        self.chatbox.connect('new-message', self._search_entry_on_new_message_cb)

        super(Chat, self).__init__(handle)

        self._entry = None
        self._has_alert = False

        self._setup_canvas()

        self._entry.grab_focus()

        toolbar_box = ToolbarBox()
        self.set_toolbar_box(toolbar_box)

        self._activity_toolbar_button = ActivityToolbarButton(self)
        self._activity_toolbar_button.connect('clicked', self._fixed_resize_cb)

        toolbar_box.toolbar.insert(self._activity_toolbar_button, 0)
        self._activity_toolbar_button.show()

        self.search_entry = iconentry.IconEntry()
        self.search_entry.set_size_request(Gdk.Screen.width() / 3, -1)
        self.search_entry.set_icon_from_name(iconentry.ICON_ENTRY_PRIMARY, 'entry-search')
        self.search_entry.add_clear_button()
        self.search_entry.connect('activate', self._search_entry_activate_cb)
        self.search_entry.connect('changed', self._search_entry_activate_cb)

        self.connect('key-press-event', self._search_entry_key_press_cb)

        self._search_item = Gtk.ToolItem()
        self._search_item.add(self.search_entry)
        toolbar_box.toolbar.insert(self._search_item, -1)

        self._search_prev = ToolButton('go-previous-paired')
        self._search_prev.set_tooltip(_('Previous'))
        self._search_prev.props.accelerator = "<Shift><Ctrl>g"
        self._search_prev.connect('clicked', self._search_prev_cb)
        self._search_prev.props.sensitive = False
        toolbar_box.toolbar.insert(self._search_prev, -1)

        self._search_next = ToolButton('go-next-paired')
        self._search_next.set_tooltip(_('Next'))
        self._search_next.props.accelerator = "<Ctrl>g"
        self._search_next.connect('clicked', self._search_next_cb)
        self._search_next.props.sensitive = False
        toolbar_box.toolbar.insert(self._search_next, -1)

        separator = Gtk.SeparatorToolItem()
        separator.props.draw = False
        separator.set_expand(True)
        toolbar_box.toolbar.insert(separator, -1)

        # Adding "Chat with me" button
        chat_button = Gtk.Button(label="Chat with me")
        chat_button.connect("clicked", self._chat_with_me_clicked)
        toolbar_box.toolbar.insert(chat_button, -1)

        toolbar_box.toolbar.insert(StopButton(self), -1)
        toolbar_box.show_all()

        # Chat is room or one to one:
        self._chat_is_room = False
        self.text_channel = None

        self.element = Gst.ElementFactory.make('playbin', 'Player')

        if self.shared_activity:
            # we are joining the activity following an invite
            self._alert(_('Off-line'), _('Joining the Chat.'))
            self._entry.props.placeholder_text = _('Please wait for a connection before starting to chat.')
            self.connect('joined', self._joined_cb)
            if self.get_shared():
                # we have already joined
                self._joined_cb(self)
        elif handle.uri:
            # XMPP non-sugar3 incoming chat, not sharable
            self._activity_toolbar_button.props.page.share.props.visible = False
            self._one_to_one_connection(handle.uri)
        else:
            # we are creating the activity
            if not self.metadata or self.metadata.get('share-scope', activity.SCOPE_PRIVATE) == activity.SCOPE_PRIVATE:
                # if we are in private session
                self._alert(_('Off-line'), _('Share, or invite someone.'))
            else:
                # resume of shared activity from journal object without invite
                self._entry.props.placeholder_text = _('Please wait for a connection before starting to chat.')
            self.connect('shared', self._shared_cb)

    def _chat_with_me_clicked(self, button):
        # Add your chat with me functionality here
        pass

    def _search_entry_key_press_cb(self, activity, event):
        keyname = Gdk.keyval_name(event.keyval).lower()
        if keyname == 'f':
            if Gdk.ModifierType.CONTROL_MASK & event.state:
                self.search_entry.grab_focus()
        elif keyname == 'escape':
            self.search_entry.props.text = ''
            self._entry.grab_focus()

    def _search_entry_on_new_message_cb(self, chatbox):
        self._search_entry_activate_cb(self.search_entry)

    def _search_entry_activate_cb(self, entry):
        for i in range(0, self.chatbox.number_of_textboxes()):
            textbox = self.chatbox.get_textbox(i)
            _buffer = textbox.get_buffer()
            start_mark = _buffer.get_mark('start')
            end_mark = _buffer.get_mark('end')
            if start_mark is None or end_mark is None:
                continue
            _buffer.delete_mark(start_mark)
            _buffer.delete_mark(end_mark)
            self.chatbox.highlight_text = (None, None, None)
        self.chatbox.set_search_text(entry.props.text)
        self._update_search_buttons()

    def _update_search_buttons(self,
