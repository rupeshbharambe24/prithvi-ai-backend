"""Named Entity Recognition for climate-health domain.

Uses spaCy NER (trained model) as primary extractor, supplemented by
domain-specific dictionary matching for specialized biomedical terms.
Falls back to dictionary-only if spaCy is unavailable.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ── spaCy model (lazy-loaded) ─────────────────────────────────────────

_nlp = None
_spacy_available: Optional[bool] = None


def _get_nlp():
    """Lazy-load spaCy model."""
    global _nlp, _spacy_available
    if _spacy_available is False:
        return None
    if _nlp is not None:
        return _nlp
    try:
        import spacy
        _nlp = spacy.load("en_core_web_sm")
        _spacy_available = True
        logger.info("spaCy en_core_web_sm loaded for NER")
        return _nlp
    except Exception as e:
        logger.warning("spaCy unavailable (%s), using dictionary NER only", e)
        _spacy_available = False
        return None


# ── Domain-specific entity dictionaries ────────────────────────────────
# These cover specialized climate-health terms that general spaCy misses

DISEASES = {
    "dengue": "Disease", "malaria": "Disease", "chikungunya": "Disease",
    "cholera": "Disease", "typhoid": "Disease", "leptospirosis": "Disease",
    "diarrhea": "Disease", "diarrhoea": "Disease", "dysentery": "Disease",
    "heatstroke": "Disease", "heat stroke": "Disease", "heat exhaustion": "Disease",
    "respiratory disease": "Disease", "asthma": "Disease", "copd": "Disease",
    "cardiovascular disease": "Disease", "hypertension": "Disease",
    "kidney disease": "Disease", "renal failure": "Disease",
    "japanese encephalitis": "Disease", "kala-azar": "Disease",
    "leishmaniasis": "Disease", "filariasis": "Disease",
    "pneumonia": "Disease", "bronchitis": "Disease",
    "gastroenteritis": "Disease", "hepatitis": "Disease",
    "dehydration": "Disease", "skin infection": "Disease",
}

CLIMATE_DRIVERS = {
    "temperature": "Driver", "heat wave": "Driver", "heatwave": "Driver",
    "humidity": "Driver", "rainfall": "Driver", "precipitation": "Driver",
    "monsoon": "Driver", "flood": "Driver", "flooding": "Driver",
    "drought": "Driver", "cyclone": "Driver", "storm": "Driver",
    "sea level rise": "Driver", "urban heat island": "Driver",
    "pm2.5": "Driver", "pm10": "Driver", "particulate matter": "Driver",
    "air pollution": "Driver", "ozone": "Driver", "no2": "Driver",
    "wet bulb temperature": "Driver", "wbgt": "Driver",
    "heat index": "Driver", "climate change": "Driver",
    "global warming": "Driver", "el nino": "Driver", "la nina": "Driver",
    "extreme weather": "Driver", "thermal stress": "Driver",
}

INTERVENTIONS = {
    "cooling center": "Intervention", "cooling centre": "Intervention",
    "early warning": "Intervention", "early warning system": "Intervention",
    "vector control": "Intervention", "bed net": "Intervention",
    "insecticide": "Intervention", "vaccination": "Intervention",
    "air quality monitoring": "Intervention", "water treatment": "Intervention",
    "sanitation": "Intervention", "public health campaign": "Intervention",
    "heat action plan": "Intervention", "emergency response": "Intervention",
    "surveillance": "Intervention", "health infrastructure": "Intervention",
    "adaptation": "Intervention", "mitigation": "Intervention",
    "green infrastructure": "Intervention", "urban planning": "Intervention",
}

POPULATIONS = {
    "elderly": "Population", "children": "Population", "infants": "Population",
    "pregnant women": "Population", "outdoor workers": "Population",
    "slum dwellers": "Population", "urban poor": "Population",
    "rural population": "Population", "agricultural workers": "Population",
    "vulnerable population": "Population", "indigenous": "Population",
    "marginalized": "Population", "low income": "Population",
}

ALL_ENTITIES: Dict[str, str] = {}
ALL_ENTITIES.update(DISEASES)
ALL_ENTITIES.update(CLIMATE_DRIVERS)
ALL_ENTITIES.update(INTERVENTIONS)
ALL_ENTITIES.update(POPULATIONS)

# Map spaCy labels to our domain types
SPACY_LABEL_MAP = {
    "ORG": "Organization",
    "GPE": "Location",
    "LOC": "Location",
    "PERSON": "Person",
    "DATE": "Date",
    "NORP": "Population",
}

# Causal relation patterns
CAUSAL_PATTERNS = [
    (r"(\w[\w\s]*?)\s+(?:causes?|leads?\s+to|results?\s+in|triggers?)\s+(\w[\w\s]*?)(?:\.|,|;|$)", "CAUSES"),
    (r"(\w[\w\s]*?)\s+(?:exacerbates?|worsens?|amplifies?|intensifies?)\s+(\w[\w\s]*?)(?:\.|,|;|$)", "EXACERBATES"),
    (r"(\w[\w\s]*?)\s+(?:reduces?|mitigates?|prevents?|decreases?)\s+(\w[\w\s]*?)(?:\.|,|;|$)", "MITIGATES"),
    (r"(\w[\w\s]*?)\s+(?:is\s+associated\s+with|correlates?\s+with|linked\s+to)\s+(\w[\w\s]*?)(?:\.|,|;|$)", "ASSOCIATED_WITH"),
    (r"(\w[\w\s]*?)\s+(?:increases?\s+risk\s+of|risk\s+factor\s+for)\s+(\w[\w\s]*?)(?:\.|,|;|$)", "RISK_FACTOR"),
    (r"(\w[\w\s]*?)\s+(?:protects?\s+against|protective\s+against)\s+(\w[\w\s]*?)(?:\.|,|;|$)", "MITIGATES"),
]


def _spacy_extract(text: str) -> List[Tuple[str, str]]:
    """Extract entities using spaCy trained NER model."""
    nlp = _get_nlp()
    if nlp is None:
        return []

    doc = nlp(text)
    entities = []
    seen = set()

    for ent in doc.ents:
        label = SPACY_LABEL_MAP.get(ent.label_, ent.label_)
        key = ent.text.lower().strip()
        if key and key not in seen and len(key) > 2:
            entities.append((key, label))
            seen.add(key)

    return entities


def _dictionary_extract(text: str) -> List[Tuple[str, str]]:
    """Extract entities using domain-specific dictionary matching."""
    text_lower = text.lower()
    found: List[Tuple[str, str]] = []
    seen: Set[str] = set()

    sorted_entities = sorted(ALL_ENTITIES.items(), key=lambda x: len(x[0]), reverse=True)
    for entity_text, entity_type in sorted_entities:
        if entity_text in text_lower and entity_text not in seen:
            found.append((entity_text, entity_type))
            seen.add(entity_text)

    return found


def extract_entities(text: str) -> List[Tuple[str, str]]:
    """Extract named entities using spaCy + domain dictionaries.

    Combines spaCy's trained NER (for general entities like locations,
    organizations, dates) with domain dictionaries (for specialized
    biomedical/climate terms that spaCy misses).

    Returns list of (entity_text, entity_type) tuples.
    """
    # Get entities from both sources
    spacy_ents = _spacy_extract(text)
    dict_ents = _dictionary_extract(text)

    # Merge: dictionary entities take priority for type classification
    # (more domain-specific), then add spaCy entities not already found
    merged: List[Tuple[str, str]] = []
    seen: Set[str] = set()

    # Domain dictionary first (more precise types)
    for ent_text, ent_type in dict_ents:
        if ent_text not in seen:
            merged.append((ent_text, ent_type))
            seen.add(ent_text)

    # Then spaCy (general NER for entities dictionaries miss)
    for ent_text, ent_type in spacy_ents:
        if ent_text not in seen:
            merged.append((ent_text, ent_type))
            seen.add(ent_text)

    return merged


def extract_relations(
    text: str,
    entities: List[Tuple[str, str]],
) -> List[Tuple[str, str, str]]:
    """Extract relations between entities from text.

    Uses regex causal patterns + spaCy dependency parsing for
    more accurate relation extraction.

    Returns list of (source_entity, relation, target_entity) triples.
    """
    text_lower = text.lower()
    relations: List[Tuple[str, str, str]] = []
    seen: Set[Tuple[str, str, str]] = set()

    entity_texts = {e[0] for e in entities}

    # Check each sentence for causal patterns
    sentences = re.split(r'[.!?]+', text_lower)
    for sentence in sentences:
        sent_entities = [e for e in entity_texts if e in sentence]
        if len(sent_entities) < 2:
            continue

        # Try matching causal patterns
        for pattern, rel_type in CAUSAL_PATTERNS:
            matches = re.finditer(pattern, sentence)
            for match in matches:
                for e1 in sent_entities:
                    for e2 in sent_entities:
                        if e1 != e2 and e1 in sentence[:match.end()] and e2 in sentence[match.start():]:
                            triple = (e1, rel_type, e2)
                            if triple not in seen:
                                relations.append(triple)
                                seen.add(triple)

        # Try spaCy dependency-based relations
        nlp = _get_nlp()
        if nlp is not None and not any(r for r in relations if any(e in r for e in sent_entities)):
            try:
                doc = nlp(sentence)
                for token in doc:
                    if token.dep_ in ("nsubj", "nsubjpass") and token.head.pos_ == "VERB":
                        subj = token.text.lower()
                        verb = token.head.lemma_.lower()
                        for child in token.head.children:
                            if child.dep_ in ("dobj", "pobj", "attr"):
                                obj = child.text.lower()
                                if subj in entity_texts and obj in entity_texts:
                                    rel = _verb_to_relation(verb)
                                    triple = (subj, rel, obj)
                                    if triple not in seen:
                                        relations.append(triple)
                                        seen.add(triple)
            except Exception:
                pass

        # Co-occurrence fallback (weaker signal)
        if not any(r for r in relations if any(e in r for e in sent_entities)):
            for i, e1 in enumerate(sent_entities):
                for e2 in sent_entities[i + 1:]:
                    e1_type = ALL_ENTITIES.get(e1, "")
                    e2_type = ALL_ENTITIES.get(e2, "")
                    if e1_type != e2_type:
                        triple = (e1, "ASSOCIATED_WITH", e2)
                        if triple not in seen:
                            relations.append(triple)
                            seen.add(triple)

    return relations


def _verb_to_relation(verb: str) -> str:
    """Map a verb lemma to a relation type."""
    cause_verbs = {"cause", "lead", "trigger", "result", "produce", "induce"}
    worsen_verbs = {"exacerbate", "worsen", "amplify", "intensify", "increase"}
    reduce_verbs = {"reduce", "mitigate", "prevent", "decrease", "lower", "protect"}
    if verb in cause_verbs:
        return "CAUSES"
    if verb in worsen_verbs:
        return "EXACERBATES"
    if verb in reduce_verbs:
        return "MITIGATES"
    return "ASSOCIATED_WITH"
