# ZFSgui
ZFS file system widget for MacOS


![ZFS GUI screenshot](https://pbs.twimg.com/media/EKoFFphXUAIfD7C?format=jpg&name=medium "ZFS GUI screenshot")

### Running the app

```diff
- WARNING
- Currently, due to limitations in macOS ZFS port, this app must be run as root.
- This can pose a security risk to your system. Please make sure that you understand
- the risks associated with running applications with elevated privileges.
- In the future, this app will drop privileges to minimize the number tasks run
- as root, but currently everything is run with elevated privileged.
```

To run the app, execute the following command in terminal:
```bash
sudo ~/Applications/zfsgui.app/Contents/MacOS/zfsgui
```
You can close the terminal now - ZFSgui will continue to run in the system tray.

### Building the app

You will need to download sources for the following libraries:
- openzfsonosx/zfs

and install the following python dependencies:

- Cython (from pip)
- PyInstaller (from pip)
- pyobjc-framework-Cocoa (from pip)
- PySide2 (from pip)
- watchdog (from pip)
- rejsmont/py-libzfs (after #72 PR, freenas/py-libzfs)

First, download the sources and prepare the python environment:

```bash
mkdir -p ~/src
cd ~/src
git clone https://github.com/rejsmont/zfsgui.git
git clone https://github.com/rejsmont/py-libzfs.git
git clone https://github.com/openzfsonosx/zfs.git
mkdir -p ~/src/zfsgui/env
cd ~/src/zfsgui/env
/usr/local/bin/python3 -m venv production
source ~/src/zfsgui/env/production/bin/activate
```

Now, let's install the python dependencies:

```bash
pip install --upgrade pip
pip install cython pyobjc-framework-Cocoa pyinstaller pyside2 watchdog 
```

We need to build `py-libzfs` macOS branch and install it:

```bash
cd ~/src/py-libzfs
autoconf && ./configure
sed -i '' 's/2\.7/3\.7/' ./Makefile
make
python setup.py install
```

Finally, you can build the app bundle:

```bash
cd ~/src/zfsgui
pyinstaller zfsgui.spec
mkdir -p ~/Applications
cp -rv dist/zfsgui.app ~/Applications
```

Done!
