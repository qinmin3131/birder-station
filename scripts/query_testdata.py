import sqlite3, json
conn = sqlite3.connect("data/birder.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("""
SELECT id, filename, primary_bird_cn, scientific_name, confidence_score, quality_score, quality_details, candidates_json
FROM photos
WHERE original_path LIKE '%testdata%'
ORDER BY filename
""").fetchall()
for r in rows:
    qd = json.loads(r['quality_details']) if r['quality_details'] else {}
    cands = json.loads(r['candidates_json']) if r['candidates_json'] else []
    qs = r['quality_score'] if r['quality_score'] is not None else 'N/A'
    conf = f"{r['confidence_score']:.3f}" if r['confidence_score'] is not None else 'N/A'
    print(f"id={r['id']} {r['filename']}: {r['primary_bird_cn']} ({r['scientific_name']}) conf={conf} quality={qs} details={qd}")
    if cands:
        print("  candidates:", ", ".join(f"{c.get('cn','?')} ({c.get('sci','?')}) {c.get('score',0):.3f}" for c in cands[:3]))
