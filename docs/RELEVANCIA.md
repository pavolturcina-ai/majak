# Ako MAJÁK rozhoduje, čo je relevantné

Systém funguje na **dvoch oddelených vrstvách**. Sťahovanie je široké, výber do
Reportu je prísny. Tento dokument popisuje, podľa čoho sa rozhoduje.

---

## Vrstva 1 — Sťahovanie: berie sa (skoro) všetko

Do databázy sa uloží **všetko z časového okna behu**, nie len relevantné.
Filtrovanie je tu iba hrubé, na úrovni konektora:

| Konektor | Čo prejde | Čo neprejde |
|----------|-----------|-------------|
| **Gmail** | maily za okno; voliteľne zúžené cez `GMAIL_QUERY` (napr. `is:starred`) | `spam`, `trash`, `chats` |
| **Slack** | správy zo všetkých konverzácií, kde si členom (kanály, DM, skupinové DM), vrátane odpovedí vo vláknach | systémové (`channel_join`, `channel_leave`, `bot_message`), prázdne správy |
| **Kalendár** | eventy daného dňa | — |

> Aj „ok, vidíme sa" alebo newsletter sa **stiahne a uloží** ako `source`
> (plný text). V tejto fáze sa nič nehodnotí — ide o kompletný podklad, aby sa
> nič nestratilo a dalo sa spätne dohľadať.

---

## Vrstva 2 — Relevancia: čo pôjde do Reportu

Tu sa rozhoduje, čo je hodnotné. Robí to **LLM extrakcia**. Z každého zdroja
hľadá diskrétne „jednotky" jedného z piatich typov:

- **Rozhodnutie**, ktoré padlo
- **Úloha / akcia** — niečo treba spraviť
- **Dobrá správa / výhra**
- **Hrozba / riziko / blocker**
- **Termín / deadline**

Každá jednotka dostane **sekciu** (`top`, `decision`, `good`, `threat`,
`deleg`, `quick`, `radar`), **závažnosť** (rail) a **confidence** — podľa toho
sa radí v Reporte.

### Dve tvrdé pravidlá, čo NEprejde

1. **Grounding invariant** — jednotka musí mať **doslovný citát + lokátor**
   (timestamp / riadok / kotviaca fráza) z originálu. Ak sa nedá uzemniť na
   konkrétnu vetu, **zahodí sa**. Žiadne vymyslené fakty, ľudia ani čísla.
2. **Small talk = 0 jednotiek** — bežná konverzácia, potvrdenia, chit-chat,
   newslettre → extrakcia z nich nevytiahne nič → v Reporte sa neobjavia
   (ale v DB ostanú uložené).

---

## Príklady: áno / nie

| Vstup (útržok) | Do Reportu? | Prečo |
|----------------|:-----------:|-------|
| „Rozhodli sme, že Fathom nasadíme od pondelka." | ✅ | rozhodnutie + dá sa odcitovať → sekcia `decision` |
| „Pošli prosím zmluvu pre ACME do piatku." | ✅ | úloha + termín → `top` / `quick`, owner |
| „Klient hrozí odchodom, ak nedodáme do 15."| ✅ | hrozba + deadline → `threat`, rail `hi` |
| „Podpísali sme nový kontrakt 🎉" | ✅ | výhra → `good`, rail `win` |
| „Ok, dík, vidíme sa zajtra." | ❌ | small talk, žiadna akcia/rozhodnutie |
| Newsletter „5 tipov na produktivitu" | ❌ | žiadna jednotka viazaná na teba |
| „Myslím, že by sme mohli niekedy zvážiť X" (bez rozhodnutia/úlohy) | ⚠️ | nanajvýš `radar` (sledovať), ak sa dá odcitovať; inak nič |
| Tvrdenie, ktoré sa nedá nájsť v texte doslovne | ❌ | poruší grounding → zahodené |

---

## Dôsledky pre teba

- **Nič sa nestratí** — v DB je kompletný podklad, aj to, čo v Reporte nevidno.
- **V Reporte je len signál** — akčné, rozhodujúce, rizikové veci, vždy s citátom.
- **Keď ťa Report otravuje šumom** → sprísni kritériá / uprav prompt.
  **Keď niečo chýba** → skontroluj, či to malo doslovný citát a či to nebolo
  vyhodnotené ako small talk.

---

*Zdroj pravdy: `src/majak/llm/prompts/extract.py` (kritériá extrakcie) a
`src/majak/connectors/*.py` (filtre sťahovania).*
