import duckdb, os, glob
base = r"C:\Users\cleber.veiga\AppData\Local\Temp\shift\executions"
latest = max(glob.glob(os.path.join(base, "*")), key=os.path.getmtime)
err_files = glob.glob(os.path.join(latest, "*_on_error.duckdb"))
print("Execution:", latest)
print("Error files:", err_files)
for p in err_files:
    print("\n=== ", os.path.basename(p), " ===")
    con = duckdb.connect(p, read_only=True)
    tables = con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()
    for (t,) in tables:
        print(f"--- table {t} ---")
        cols = [c[0] for c in con.execute(f'DESCRIBE "{t}"').fetchall()]
        print("Columns:", cols)
        rows = con.execute(f'SELECT * FROM "{t}" LIMIT 3').fetchall()
        for r in rows:
            for name, val in zip(cols, r):
                print(f"  {name}: {val}")
            print("  ---")
    con.close()