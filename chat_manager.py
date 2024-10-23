class ChatManager:
    def __init__(self):
        self.channels = {}  # {channel_name: set(usernames)}

    def create_channel(self, channel_name):
        if channel_name and channel_name not in self.channels:
            self.channels[channel_name] = set()
            return True
        return False

    def get_channels(self):
        # Return list of tuples containing channel name and user count
        return [(channel, len(users)) for channel, users in self.channels.items()]

    def add_user_to_channel(self, channel, username):
        if channel in self.channels:
            self.channels[channel].add(username)

    def remove_user_from_channel(self, channel, username):
        if channel in self.channels:
            self.channels[channel].discard(username)
