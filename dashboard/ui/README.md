# Streamlit UI

Run the UI with Python 3.12. Some geospatial packages do not provide
Windows wheels for newer Python versions yet.

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r ui\requirements.txt
.\.venv\Scripts\python.exe -m streamlit run ui\app.py
```

From this `ui` folder:

```powershell
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
..\.venv\Scripts\python.exe -m streamlit run app.py
```

The Kepler GL vector-map backend is optional. It is intentionally not in
`requirements.txt` because its dependency chain can fail to build on
newer Python versions, especially Python 3.14.
