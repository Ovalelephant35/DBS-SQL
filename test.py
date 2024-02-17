class ChatBot:
    def __init__(self):
        with open('knowledge.json', 'r') as f:
            self.knowledge = json.load(f)

    def respond(self, message):
        if message.lower() in self.knowledge:
            return self.knowledge[message.lower()]
        else:
            return "Sorry, I don't understand."

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

        # Add button to chat with AI
        self._ai_button = ToolButton.new('chat-with-ai')
        self._ai_button.set_tooltip_text('Chat with AI')
        self._ai_button.connect('clicked', self._ai_button_clicked_cb)
        toolbar_box.toolbar.insert(self._ai_button, -1)
        self._ai_button.show()

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
            self._activity_toolbar_button.props.page.share.props