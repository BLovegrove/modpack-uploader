class server:
    # Public IP address for the system your pack is hosted on
    host = "xxx.xxx.xxx.xxx"
    # SSH-FTP (SFTP) port (must be forwarded!) on the host system you pack lives on. Usually default unless you changed it.
    port = 22
    # Username and password for the user account you are using SSH to access.
    username = "admin"
    password = "password"
    # Path to the folder you want your modpack version folders to live. This is usually the same as the path in your URL setting above.
    # I would recommend using nginx to host it on /var/www/<something> or similar. This program does not work with dropbox etc. Only something accessable via SFTP.
    filepath = "My Modpack/"


class exe:
    # Version number to include in compiled executable - use to differentiate versions where user might already have an old one
    version = "1.0"
