from cx_Freeze import setup, Executable
import config as cfg

# Dependencies are automatically detected, but it might need
# fine tuning.

build_options = {
    "packages": [],
    "excludes": [],
    "build_exe": "build",
}
# build_options = {"packages": [], "excludes": [], }

setup(
    name="modpack-uploader",
    version=f"{cfg.exe.version}",
    description=f"Uploads new version of your chosen modpack",
    options={"build_exe": build_options},
    executables=[
        Executable("./update/__main__.py", base="Console", target_name="modpack-upload")
    ],
)
