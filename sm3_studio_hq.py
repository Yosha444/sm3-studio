# SPDX-License-Identifier: GPL-3.0-or-later
"""SM3 Studio entry point: `python sm3_studio_hq.py`, and the entry script of SM3 Studio.exe.

What happens at start-up:
  1. Without command-line arguments, a small window asks for the interface language
     (studio_language.choose; the answer is remembered in language.txt next to the .exe, or next
     to this file when run from source). With arguments, the language is French and no window
     is shown at all.
  2. sm3_interface.py (the main window) and sm3_gui_hq.py (the HQ additions) are compiled from
     their source and, for English, passed through studio_language.localize(), which translates
     their string constants. That is why they are executed here instead of being imported.
  3. sm3_gui_hq.integrate() patches the Studio class of sm3_interface.py.
  4. With arguments: convert without a window (sm3_interface._sans_fenetre), e.g.
         "SM3 Studio.exe" --nom MyMod --src model.glb
     Without: open the window.

When frozen by PyInstaller (construire/SM3Studio.spec), sys._MEIPASS is the folder where the
.exe unpacked its bundled files: sm3_interface.py, sm3_gui_hq.py and the converter modules are
read from there, so editing them on disk changes nothing until the .exe is rebuilt.
"""
import os
import sys

# Folder holding the bundled .py files: inside the .exe when frozen, next to this file otherwise.
base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, base)
from studio_language import choose, localize


def run_source(file_name, module_name, language):
    """Compile base/<file_name>, translate it for English, execute it; return its globals."""
    path = os.path.join(base, file_name)
    with open(path, encoding='utf-8-sig') as f:
        code = compile(f.read(), path, 'exec')
    namespace = {'__name__': module_name, '__file__': path}
    exec(localize(code) if language == 'en' else code, namespace)
    return namespace


# The language window needs a display; the command-line mode must run without one.
if len(sys.argv) == 1:
    language = choose(os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else base)
else:
    language = 'fr'
# Read back by sm3_gui_hq to show the saved target character in the right language.
os.environ['SM3_UI_LANGUAGE'] = language

# __name__ is not '__main__', so the `if __name__ == '__main__'` block of sm3_interface.py does
# not run: this script opens the window itself, after the HQ patch.
interface = run_source('sm3_interface.py', 'sm3_interface', language)
hq = run_source('sm3_gui_hq.py', 'sm3_gui_hq', language)
Studio = hq['integrate'](interface)

if len(sys.argv) > 1:
    interface['_sans_fenetre'](sys.argv[1:])
else:
    app = Studio()

    def close():
        # The HQ _sauver validates the quality settings: on an invalid value, explain and keep
        # the window open instead of losing the settings. (This title is not passed through
        # localize(), so it stays French in English mode, as in every build so far.)
        try:
            app._sauver()
        except (ValueError, OSError) as error:
            interface['messagebox'].showerror('Réglages HQ', str(error), parent=app)
            return
        app.destroy()
    app.protocol('WM_DELETE_WINDOW', close)
    app.mainloop()
