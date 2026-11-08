def split_fields(text):
    return [value.strip() for value in text.split("|") if value.strip()]


catalog = {row["id"]: row for row in csv.DictReader(StringIO(CATALOG_CSV))}
product_lookup = {normalize(row["product"]): key for key, row in catalog.items()}
assert catalog and len(catalog) == len(product_lookup)

INGREDIENTS = {key: frozenset(split_fields(row["normalized_active_ingredients"])) for key, row in catalog.items()}
USES = {key: frozenset(split_fields(row["covered_label_uses"])) for key, row in catalog.items()}
NSAIDS = {"aspirin", "ibuprofen", "naproxen"}

AGE_OPTIONS = ("18–59", "60 or older", "Under 18", "Unsure")
RISK_OPTIONS = (
    "None of these", "Liver disease", "Liver cirrhosis", "Stomach ulcers or bleeding",
    "High blood pressure", "Taking a blood thinner", "Taking an MAOI", "Medication allergy",
    "Pregnant or breastfeeding", "Other or unsure",
)
RISK_RULES = {
    "Liver disease": ("liver_disease_warning", "The label says to ask a doctor before use if you have liver disease."),
    "Liver cirrhosis": ("liver_cirrhosis_warning", "The label says to ask a doctor before use if you have liver cirrhosis."),
    "Stomach ulcers or bleeding": ("stomach_ulcer_warning", "The label warns about stomach bleeding and lists a history of ulcers or bleeding as a risk factor."),
    "High blood pressure": ("high_blood_pressure_warning", "The label says to ask a doctor first if you have high blood pressure."),
    "Taking a blood thinner": ("blood_thinner_warning", "The label includes a warning for people taking a blood thinner."),
    "Taking an MAOI": ("maoi_warning", "The label says to avoid this product during MAOI use and for two weeks after stopping it."),
    "Pregnant or breastfeeding": ("pregnancy_breastfeeding_warning", "The label has a pregnancy and breastfeeding warning. See the exact wording on the label."),
}
CASE_ACTIONS = ("Change current medicines", "Change health factors", "Start over")
CASE_REVIEW = (
    "Ask a pharmacist or clinician to review the reported health factors and exact products before choosing. "
    "Follow any product label instructions to ask a doctor."
)
HELP_URL = "https://medlineplus.gov/ency/article/001927.htm"
URGENT_PHRASE = re.compile(r"\b(?:trouble breathing|difficulty breathing|shortness of breath|can t breathe|cannot breathe|chest pain)\b")


@dataclass(frozen=True)
class LabelComparison:
    key: str
    flags: tuple
    notes: tuple


@dataclass(frozen=True)
class Reply:
    text: str
    choices: tuple = ()
    sources: tuple = ()
    status: str = "question"
    comparison: tuple[LabelComparison, ...] = ()


def product_label(key):
    row = catalog[key]
    return (row["product"], row["label_url"])


def matching_products(symptom):
    return tuple(key for key in catalog if symptom in USES[key])


def resolve_current(text):
    fields = split_fields(text)
    if len(fields) == 1 and normalize(fields[0]) == "none":
        return (), ()
    found, unresolved = [], []
    for field in fields:
        key = product_lookup.get(normalize(field))
        (found if key else unresolved).append(key or field)
    return tuple(dict.fromkeys(found)), tuple(unresolved or (["No answer supplied"] if not fields else []))


INTAKE_EXAMPLE = (
    "I'm 28 and have a headache. I took Tylenol Extra Strength tablets. "
    "None of the listed health factors apply."
)
AGE_MENTION = re.compile(r"\b(?:(?:i m|i am|age|aged) (\d{1,3})|(\d{1,3}) years? old)\b")
MEDICINE_MENTION = re.compile(
    r"\b(?:i (?:already )?(?:took|take|have taken|am taking|m taking)|"
    r"current (?:medicines|medications)(?: are)?)\s+(.+)$"
)
MEDICINE_TIME = re.compile(
    r"\s+(?:earlier today|this morning|this afternoon|last night|yesterday|today|earlier)$"
)
NO_MEDICINES = {
    "no meds", "no medicines", "no medications", "i haven t taken anything",
    "i have not taken anything", "i don t take any medicine", "i don t take any medications",
    "i m not taking any medication", "i m not taking any medicine", "current medicines none",
}
NO_HEALTH_FACTORS = {
    "none of the listed health factors apply", "none of these health factors apply",
    "no listed health factors", "health factors none", "none of these apply",
}
RISK_LOOKUP = {normalize(option): option for option in RISK_OPTIONS}


def age_group(age):
    if age < 18:
        return "Under 18"
    if age <= 59:
        return "18–59"
    return "60 or older" if age <= 120 else None


@dataclass(frozen=True)
class IntakeDraft:
    symptom_text: str
    age: str | None
    medicines: tuple | None
    unresolved: tuple
    risks: tuple
    has_details: bool


def parse_intake(text):
    # Use explicit role phrases so a product someone is considering is not recorded as taken.
    raw_clauses = re.split(r"[.!?;\n]+|\band\s+(?=i\b)", text, flags=re.I)
    ages = {int(first or second) for first, second in AGE_MENTION.findall(normalize(text))}
    age = age_group(next(iter(ages))) if len(ages) == 1 else None
    # A first-person age is not enough to identify the age of a different person.
    if re.search(r"\b(?:my child|my kid|my son|my daughter|my parent|my mom|my dad|my partner)\b", normalize(text)):
        age = None

    symptom_parts = []
    medicine_lists = []
    no_medicines = False
    risks = []
    no_risks = False
    for raw_clause in raw_clauses:
        clause = normalize(raw_clause)
        symptom_clause = clause
        if clause in NO_MEDICINES:
            no_medicines = True
            symptom_clause = ""
        else:
            medicine_clause = normalize(re.sub(r"[,|]", " and ", raw_clause))
            if match := MEDICINE_MENTION.search(medicine_clause):
                symptom_clause = medicine_clause[:match.start()]
                for item in re.split(r"\s+and\s+", match.group(1)):
                    medicine_lists.append(MEDICINE_TIME.sub("", item))

        if clause in NO_HEALTH_FACTORS:
            no_risks = True
            symptom_clause = ""
        else:
            for pattern in (
                r"health factors(?: are)? (.+)",
                r"i (?:have|was diagnosed with) (.+)",
                r"i (?:am|m) (pregnant|breastfeeding)",
                r"i (?:take|am taking|m taking) (a blood thinner|an maoi)",
            ):
                match = re.fullmatch(pattern, clause)
                if not match:
                    continue
                term = match.group(1)
                term = {
                    "pregnant": "pregnant or breastfeeding",
                    "breastfeeding": "pregnant or breastfeeding",
                    "a blood thinner": "taking a blood thinner",
                    "an maoi": "taking an maoi",
                }.get(term, term)
                fields = re.split(r"\s+and\s+", term)
                known = [RISK_LOOKUP[field] for field in fields if field in RISK_LOOKUP]
                if known and len(known) != len(fields):
                    known.append("Other or unsure")
                elif known:
                    symptom_clause = ""
                risks.extend(known)
        symptom_clause = AGE_MENTION.sub("", symptom_clause)
        for product in product_lookup:
            symptom_clause = re.sub(rf"\b{re.escape(product)}\b", "", symptom_clause)
        if symptom_clause.strip():
            symptom_parts.append(symptom_clause.strip())

    found, unresolved = resolve_current(" | ".join(medicine_lists)) if medicine_lists else ((), ())
    # If the message conflicts with itself, leave the field open for clarification.
    if no_medicines and medicine_lists:
        medicines, unresolved = None, ()
    else:
        medicines = found if medicine_lists or no_medicines else None
    positive_risks = tuple(dict.fromkeys(risk for risk in risks if risk != "None of these"))
    if (no_risks or "None of these" in risks) and positive_risks:
        confirmed_risks = ()
    else:
        confirmed_risks = positive_risks or (("None of these",) if no_risks or risks else ())
    return IntakeDraft(" ".join(symptom_parts), age, medicines, unresolved, confirmed_risks, bool(
        ages or medicine_lists or no_medicines or no_risks or risks
    ))


def intake_symptom(text, matcher):
    message = normalize(text)
    if not message:
        return None
    literal = [name for name in SYMPTOMS if re.search(rf"\b{re.escape(name)}\b", message)]
    if len(literal) == 1:
        symptom = literal[0]
        negated = re.search(rf"\b(?:no|without|never had|don t have|do not have) (?:a |any )?{re.escape(symptom)}\b", message)
        return None if negated else symptom
    if len(literal) > 1:
        return None
    guess = matcher(text)
    return guess if guess in SYMPTOMS else None


def label_findings(age, current, risks, candidate):
    row = catalog[candidate]
    ingredients = INGREDIENTS[candidate]
    duplicate = sorted(ingredients & set().union(*(INGREDIENTS[key] for key in current)))
    flags = []
    if duplicate:
        overlaps = [
            f"{catalog[key]['product']} ({', '.join(sorted(ingredients & INGREDIENTS[key]))})"
            for key in current if ingredients & INGREDIENTS[key]
        ]
        flags.append("Shared active ingredient(s): " + ", ".join(duplicate) + ". Overlap with " + ", ".join(overlaps) + ".")
        if "acetaminophen" in duplicate and row["acetaminophen_overlap_warning"] == "1":
            flags.append("The label warns against combining it with another acetaminophen product.")
        else:
            flags.append("Ask a pharmacist before combining these products.")

    if row["nsaid_overlap_warning"] == "1" and any(INGREDIENTS[key] & NSAIDS for key in current):
        flags.append("The reported medicines include another NSAID, a stomach-bleeding risk factor listed on this label.")
    if age == "60 or older" and row["age_60_bleeding_warning"] == "1":
        flags.append("The label lists age 60 or older as a factor that raises the chance of stomach bleeding.")
    relevant_risks = set(risks)
    if "Liver cirrhosis" in relevant_risks:
        relevant_risks.add("Liver disease")
    for risk, (field, message) in RISK_RULES.items():
        if risk in relevant_risks and row[field] == "1":
            flags.append(message)

    notes = []
    if "Liver disease" in risks and "Liver cirrhosis" not in risks and row["liver_cirrhosis_warning"] == "1":
        notes.append(
            "This label says to ask a doctor before use if you have liver cirrhosis. "
            "You reported liver disease. Whether this specific warning applies needs clarification."
        )
    if row["drowsiness_warning"] == "1":
        notes.append("Label warns about drowsiness.")
    status = "shared_ingredient" if duplicate else "label_warning" if flags else "label_match"
    return tuple(flags), tuple(notes), status


def compare_labels(symptom, age, current, risks, candidate):
    if age not in AGE_OPTIONS[:2] or symptom not in USES[candidate]:
        return Reply("The age or symptom falls outside this comparison.", status="outside_scope")

    row = catalog[candidate]
    flags, notes, status = label_findings(age, current, risks, candidate)
    current_summary = ", ".join(catalog[key]["product"] for key in current) or "none reported"
    risk_summary = ", ".join(risks) or "not supplied"
    use_description = (
        f"{row['product']}'s label describes loosening mucus and thinning bronchial secretions."
        if symptom == "chest congestion" else f"{row['product']} lists {symptom} among its uses."
    )
    lines = [
        use_description,
        f"Case details: age {age}. Current medicines: {current_summary}. Selected health factors: {risk_summary}.",
        "Active ingredients: " + ", ".join(sorted(INGREDIENTS[candidate])) + ".",
        *(flags + notes or ("No case-specific flag appeared in the selected checks.",)),
    ]
    if risks != ("None of these",):
        lines.append(CASE_REVIEW)
    lines.append("This is a limited label comparison. Suitability, dose, timing, and other interactions need separate review.")
    return Reply(
        "\n".join(lines),
        choices=("Compare another product", *CASE_ACTIONS),
        sources=tuple(product_label(key) for key in dict.fromkeys([candidate, *current])),
        status=status,
    )


class Chat:
    def __init__(self, matcher=suggest_symptom):
        self.matcher = matcher
        self.reset()

    def reset(self):
        self.stage = "symptom"
        self.symptom = self.age = None
        self.current = self.risks = ()
        self.one_message = False
        self.current_known = False
        self.unresolved_current = ()
        return Reply(
            "Describe your symptom, age, and medicines already taken in one message, "
            "or start with a symptom and answer one question at a time."
        )

    def ask_current(self, text=None):
        self.stage = "current"
        if self.unresolved_current:
            name = self.unresolved_current[0]
            choices = tuple(
                row["product"] for row in catalog.values()
                if f" {normalize(name)} " in f" {normalize(row['product'])} "
            )
            if not choices:
                choices = tuple(row["product"] for row in catalog.values())
            return Reply(
                f'Which exact package did you mean by "{name}"? Choose or type its displayed name. '
                "If it is outside this catalog, bring the package to a pharmacist for comparison.",
                (*choices, "Start over"),
                status="verify_product",
            )
        return Reply(
            text or "Which medicines are already in use? Select the exact package below. For multiple products, type their exact displayed names separated by |.",
            ("None", "I am unsure", *(row["product"] for row in catalog.values())),
        )

    def ask_age(self):
        self.stage = "age"
        return Reply("What is the age for this case? Type it or select a range.", AGE_OPTIONS)

    def continue_intake(self):
        if self.symptom is None:
            self.stage = "confirm"
            return Reply("Which one symptom should I compare labels for?", (*SYMPTOMS, "Something else"), status="confirm_symptom")
        if self.age is None:
            return self.ask_age()
        if self.age not in AGE_OPTIONS[:2]:
            self.stage = "end"
            return Reply("This demo compares adult labels and needs a confirmed adult age range.", ("Start over",), status="outside_scope")
        if not self.current_known or self.unresolved_current:
            return self.ask_current()
        if not self.risks:
            return self.ask_risk()

        self.stage = "intake_review"
        medicines = ", ".join(catalog[key]["product"] for key in self.current) or "None reported"
        return Reply(
            "Check the details I picked up before I compare the labels.\n"
            f"Symptom: {self.symptom} · Age: {self.age}\n"
            f"Medicines already taken: {medicines}\n"
            f"Health factors: {', '.join(self.risks)}",
            ("Confirm details", *CASE_ACTIONS),
            status="confirm_intake",
        )

    def ask_risk(self):
        self.stage = "risk"
        return Reply(
            "Choose the health factors you already know apply, or select Other or unsure. "
            "To list more than one, separate the options with |.",
            RISK_OPTIONS,
        )

    def ask_candidate(self, text=None):
        self.stage = "candidate"
        results = []
        for key in matching_products(self.symptom):
            flags, notes, _ = label_findings(self.age, self.current, self.risks, key)
            results.append(LabelComparison(key, flags, notes))

        # Put case-specific warnings first, then order by name within each group.
        results.sort(key=lambda row: (not bool(row.flags), catalog[row.key]["product"].lower()))
        flagged = sum(bool(row.flags) for row in results)
        current = ", ".join(catalog[key]["product"] for key in self.current) or "none reported"
        selected_risks = ", ".join(self.risks)
        summary = [
            f"Label comparison for {self.symptom} · {len(results)} products · {flagged} with case-specific flags.",
            f"Age {self.age} · Current medicines: {current} · Health factors: {selected_risks}.",
        ]
        if self.risks != ("None of these",):
            summary.append(CASE_REVIEW)
        summary.append(text or "Review the table below or select a product for details. The checks cover only selected label warnings.")
        options = tuple(catalog[row.key]["product"] for row in results)
        return Reply(
            "\n".join(summary),
            (*options, *CASE_ACTIONS),
            sources=tuple(product_label(key) for key in self.current),
            status="comparison",
            comparison=tuple(results),
        )

    def submit(self, text):
        text = text.strip()
        value = normalize(text)
        if value == "start over":
            return self.reset()
        if self.stage in {"candidate", "result", "intake_review"}:
            if value == "change current medicines":
                self.current = ()
                self.current_known = False
                self.unresolved_current = ()
                return self.ask_current()
            if value == "change health factors":
                return self.ask_risk()

        if self.stage == "symptom":
            if not value:
                return Reply("Enter a symptom to continue.")
            if URGENT_PHRASE.search(value):
                self.stage = "end"
                return Reply(
                    "You mentioned a possible emergency symptom. Seek emergency help now. In the U.S., call 911.",
                    ("Start over",), (("MedlinePlus emergency signs", HELP_URL),), "urgent",
                )
            draft = parse_intake(text)
            if draft.has_details:
                self.one_message = True
                self.symptom = intake_symptom(draft.symptom_text, self.matcher)
                self.age = draft.age
                self.current = draft.medicines or ()
                self.current_known = draft.medicines is not None
                self.unresolved_current = draft.unresolved
                self.risks = draft.risks
                return self.continue_intake()
            guess = self.matcher(text)
            self.stage = "confirm"
            prompt = (
                f"Did you mean {guess}? Please confirm using the dropdown or type the category, then press Send."
                if guess != OUTSIDE else "I couldn't match that description. Choose a category if one fits."
            )
            choices = tuple(dict.fromkeys((guess, *SYMPTOMS))) if guess in SYMPTOMS else SYMPTOMS
            return Reply(prompt, (*choices, "Something else"), status="confirm_symptom")

        if self.stage == "confirm":
            if value == "something else":
                self.stage = "end"
                return Reply("This demo covers only the seven listed symptoms.", ("Start over",), status="outside_scope")
            if value not in SYMPTOMS:
                return Reply("Please select one symptom category.", (*SYMPTOMS, "Something else"), status="confirm_symptom")
            self.symptom = value
            return self.continue_intake() if self.one_message else self.ask_age()

        if self.stage == "age":
            age_by_text = {normalize(age): age for age in AGE_OPTIONS}
            self.age = age_group(int(value)) if re.fullmatch(r"[0-9]{1,3}", value) else age_by_text.get(value)
            if self.age is None:
                return self.ask_age()
            if self.age not in AGE_OPTIONS[:2]:
                self.stage = "end"
                return Reply("This demo compares adult labels and needs a confirmed adult age range.", ("Start over",), status="outside_scope")
            return self.continue_intake() if self.one_message else self.ask_current()

        if self.stage == "current":
            found, unresolved = resolve_current(text)
            if self.unresolved_current:
                if unresolved or len(found) != 1:
                    return self.ask_current()
                self.current = tuple(dict.fromkeys((*self.current, *found)))
                self.unresolved_current = self.unresolved_current[1:]
                return self.continue_intake()
            self.current = found
            if unresolved:
                prompt = "I need the exact medicine name and formulation before comparing labels. Choose a listed product, or ask a pharmacist if the package is unclear or outside this catalog."
                reply = self.ask_current(prompt)
                return Reply(reply.text, reply.choices, status="verify_product")
            self.current_known = True
            return self.continue_intake() if self.one_message else self.ask_risk()

        if self.stage == "risk":
            risks = tuple(dict.fromkeys(RISK_LOOKUP.get(normalize(field)) for field in split_fields(text)))
            if not risks or None in risks or ("None of these" in risks and len(risks) > 1):
                return Reply("Please select a listed factor or choose Other or unsure.", RISK_OPTIONS)
            self.risks = risks
            return self.continue_intake() if self.one_message else self.ask_candidate()

        if self.stage == "intake_review":
            if value in {"confirm details", "confirm", "yes"}:
                self.one_message = False
                return self.ask_candidate()
            return self.continue_intake()

        if self.stage == "candidate":
            key = product_lookup.get(value)
            if key not in matching_products(self.symptom):
                return self.ask_candidate("Please select an exact label from the products listed for this symptom.")
            self.stage = "result"
            return compare_labels(self.symptom, self.age, self.current, self.risks, key)

        if self.stage == "result":
            if value == "compare another product":
                return self.ask_candidate()
            return Reply(
                "Choose another product, update the case details, or start over.",
                ("Compare another product", *CASE_ACTIONS),
            )

        return Reply("Start over to begin a new comparison.", ("Start over",))
