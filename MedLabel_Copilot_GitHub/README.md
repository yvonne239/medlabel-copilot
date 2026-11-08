# MedLabel Copilot

MedLabel Copilot is an interactive notebook for comparing selected information from exact U.S. over-the-counter drug labels. It explores whether semantic matching can recognize everyday descriptions of symptoms while keeping the label comparison traceable to its source.

## Try the notebook

1. Download [MedLabel_Copilot.ipynb](MedLabel_Copilot.ipynb) and upload it to [Google Colab](https://colab.research.google.com/).
2. Choose **Runtime → Run all** and scroll to **Section 4**.
3. Click **Try one message**. Review the fictional case, then enter **Confirm details** to see the comparison.
4. Try entering only a brand name to see how the chatbot asks for the exact formulation. **Try cough comparison** loads a second fictional case with an ingredient-overlap example.

The first run may download a 22 MB model. The notebook embeds the label catalog and uses a TF-IDF fallback if the optional model is unavailable.

## How it works

The chatbot recognizes a symptom using exact matching or semantic similarity. MiniLM and TF-IDF are evaluated against the same synthetic language cases. For a multi-detail message, a parser extracts supported details and asks for clarification when information is missing or the medicine name is ambiguous. Once the user confirms the case, deterministic rules compare the confirmed products and link each result to its versioned label.

## Evaluation

| Check | Result |
|---|---|
| Synthetic symptom paraphrases | MiniLM 14/21 · TF-IDF 11/21 |
| Literal symptom phrases | Both 7/7 |
| Out-of-scope examples | Both 10/10 |
| Scripted rule and dialogue checks | 34/34 passed |

The language benchmark uses 38 handcrafted test cases, separate from the 20 examples used to set the matching thresholds. These results describe the prototype's behavior on those examples.

## Project files

| File | Contents |
|---|---|
| [MedLabel_Copilot.ipynb](MedLabel_Copilot.ipynb) | Interactive demo, implementation, and evaluation |
| [MedLabel_DailyMed_OTC_Dataset.csv](MedLabel_DailyMed_OTC_Dataset.csv) | A catalog of 17 exact formulations with ingredients, selected warnings, and label provenance |

The catalog uses versioned Structured Product Labels from the [U.S. National Library of Medicine's DailyMed service](https://dailymed.nlm.nih.gov/dailymed/app-support-web-services.cfm). This educational prototype covers selected checks for seven adult symptoms. Use fictional examples. For questions about a real medicine, consult the full product label and a pharmacist or clinician.
