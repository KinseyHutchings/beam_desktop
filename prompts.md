# Request log

- Asked: Update `spec.md` to describe a Python desktop app using Tkinter; don't build anything.
- Changed: Clarified the Python/Tkinter desktop window, module separation, embedded Matplotlib plots, and smaller-window behavior; updated the visual reference from a web app to a desktop app.
- Worked: Yes. Documentation only; no application was built.
- Asked: Read `spec.md` and build the desktop app it describes, using `index.html` as a behavior reference.
- Changed: Added the Tkinter interface in `app.py`, separated beam calculations and section data into `calculations.py`, and listed NumPy and Matplotlib in `requirements.txt`.
- Worked: Yes. Implemented the app features from the spec; no test run was requested.
- Asked: Why is the app not opening?
- Changed: Found that `python` is not installed in this shell while `python3` is available; corrected the launch command in `spec.md` to `python3 app.py`.
- Worked: `python3 app.py` started without a traceback and remained running; `python app.py` failed with `command not found`.
