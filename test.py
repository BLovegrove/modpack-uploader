import hashlib
import paramiko
import config as cfg

ssh = paramiko.SSHClient()
ssh.load_system_host_keys()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(
    cfg.server.host,
    cfg.server.port,
    username=cfg.server.username,
    password=cfg.server.password,
)
sftp = ssh.open_sftp()
sftp.chdir(cfg.server.filepath)

config = "config/ae2/client.json"
ssh.exec_command("")
with open(config, "rb", buffering=0) as f:
    print(hashlib.file_digest(f, "sha256").hexdigest())
