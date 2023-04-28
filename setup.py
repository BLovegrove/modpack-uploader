from cx_Freeze import setup, Executable

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
    version="1.0",
    description=f"Uploads new version of your chosen modpack",
    options={"build_exe": build_options},
    executables=[
        Executable("./update/__main__.py", base="Console", target_name="modpack-upload")
    ],
)
