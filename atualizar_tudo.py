"""Roda os coletores em ordem e mostra um resumo. Uso:  python atualizar_tudo.py
Opções: --pular sih,cnes   (nomes: ibge, geo, srag, sih, cnes)
Cada coletor reaproveita arquivos já baixados em data/raw."""
import subprocess
import sys

ETAPAS = [("ibge", "collect_ibge.py"), ("geo", "collect_geo.py"), ("srag", "collect_srag.py"),
          ("sih", "collect_sih.py"), ("cnes", "collect_cnes.py")]
pular = set()
if "--pular" in sys.argv:
    pular = set(sys.argv[sys.argv.index("--pular") + 1].split(","))

resumo = []
for nome, script in ETAPAS:
    if nome in pular:
        resumo.append((nome, "pulado"))
        continue
    print(f"\n===== {nome}: {script} =====")
    ok = subprocess.run([sys.executable, script]).returncode == 0
    resumo.append((nome, "ok" if ok else "FALHOU"))

print("\n===== resumo =====")
for nome, st in resumo:
    print(f"{nome:6s} {st}")
print("\nDepois: streamlit run app.py")
