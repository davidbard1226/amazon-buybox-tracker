lines = open(r"C:\webprojects\amazon-buybox-tracker\dashboard.html", encoding="utf-8").readlines()
insert_at = 1439
lines.insert(insert_at, "\n")
lines.insert(insert_at, "  // Price movement log\n")
lines.insert(insert_at, "  const logEl = document.getElementById('intelPriceLog');\n")
lines.insert(insert_at, "  if (logEl) renderPriceLog(d.price_movements, logEl);\n")
open(r"C:\webprojects\amazon-buybox-tracker\dashboard.html", "w", encoding="utf-8").writelines(lines)
print("Done, total lines:", len(lines))
