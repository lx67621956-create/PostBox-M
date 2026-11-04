"""PostBox-M — a shared folder as the message bus between autonomous agents.

The design goal is boring reliability: no server, no database, no credentials
beyond the folder you already share. Any file-sync layer (Google Drive via
rclone, Dropbox, Syncthing, a USB stick) works, because the protocol only ever
uses "list / read / create-if-absent / replace-own-file".
"""

__version__ = "0.6.1"
PROTOCOL_VERSION = "1.1"
