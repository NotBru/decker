"""Drop pages whose content model this wiki cannot handle (Flow boards)."""
import bz2, sys
src, dst = sys.argv[1], sys.argv[2]
bad_models = ("flow-board",)
kept = dropped = 0
with bz2.open(src, "rt", encoding="utf-8") as fin, open(dst, "w", encoding="utf-8") as fout:
    block, inpage = [], False
    for line in fin:
        if "<page>" in line:
            inpage, block = True, [line]
            continue
        if inpage:
            block.append(line)
            if "</page>" in line:
                text = "".join(block)
                if any(f"<model>{m}</model>" in text for m in bad_models):
                    dropped += 1
                else:
                    fout.write(text); kept += 1
                inpage, block = False, []
            continue
        fout.write(line)
print(f"kept {kept} pages, dropped {dropped}")
