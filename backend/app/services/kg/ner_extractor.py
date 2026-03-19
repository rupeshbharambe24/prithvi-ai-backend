"""Named Entity Recognition for climate-health domain.

Uses pattern-based NER (no heavy ML dependencies required).
Optionally uses spaCy/scispaCy if available for better accuracy.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

# Domain-specific entity dictionaries
# These cover the key entities in climate-health literature

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

# Merge all entity dictionaries
ALL_ENTITIES: Dict[str, str] = {}
ALL_ENTITIES.update(DISEASES)
ALL_ENTITIES.update(CLIMATE_DRIVERS)
ALL_ENTITIES.update(INTERVENTIONS)
ALL_ENTITIES.update(POPULATIONS)

# Relation patterns (simplified dependency-based)
CAUSAL_PATTERNS = [
    (r"(\w+)\s+(?:causes?|leads?\s+to|results?\s+in|triggers?)\s+(\w+)", "CAUSES"),
    (r"(\w+)\s+(?:exacerbates?|worsens?|amplifies?|intensifies?)\s+(\w+)", "EXACERBATES"),
    (r"(\w+)\s+(?:reduces?|mitigates?|prevents?|decreases?)\s+(\w+)", "MITIGATES"),
    (r"(\w+)\s+(?:is\s+associated\s+with|correlates?\s+with|linked\s+to)\s+(\w+)", "ASSOCIATED_WITH"),
    (r"(\w+)\s+(?:increases?\s+risk\s+of|risk\s+factor\s+for)\s+(\w+)", "RISK_FACTOR"),
    (r"(\w+)\s+(?:protects?\s+against|protective\s+against)\s+(\w+)", "MITIGATES"),
]


def extract_entities(text: str) -> List[Tuple[str, str]]:
    """Extract named entities from text using pattern matching.

    Returns list of (entity_text, entity_type) tuples.
    """
    text_lower = text.lower()
    found: List[Tuple[str, str]] = []
    seen: Set[str] = set()

    # Match against entity dictionaries (longest match first)
    sorted_entities = sorted(ALL_ENTITIES.items(), key=lambda x: len(x[0]), reverse=True)
    for entity_text, entity_type in sorted_entities:
        if entity_text in text_lower and entity_text not in seen:
            found.append((entity_text, entity_type))
            seen.add(entity_text)

    return found


def extract_relations(
    text: str,
    entities: List[Tuple[str, str]],
) -> List[Tuple[str, str, str]]:
    """Extract relations between entities from text.

    Returns list of (source_entity, relation, target_entity) triples.
    """
    text_lower = text.lower()
    relations: List[Tuple[str, str, str]] = []
    seen: Set[Tuple[str, str, str]] = set()

    entity_texts = {e[0] for e in entities}

    # Check each sentence for causal patterns
    sentences = re.split(r'[.!?]+', text_lower)
    for sentence in sentences:
        # Find entities in this sentence
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

        # Co-occurrence based relations (weaker signal)
        if not any(r for r in relations if any(e in r for e in sent_entities)):
            for i, e1 in enumerate(sent_entities):
                for e2 in sent_entities[i + 1:]:
                    e1_type = ALL_ENTITIES.get(e1, "")
                    e2_type = ALL_ENTITIES.get(e2, "")
                    # Only create co-occurrence for different types
                    if e1_type != e2_type:
                        triple = (e1, "ASSOCIATED_WITH", e2)
                        if triple not in seen:
                            relations.append(triple)
                            seen.add(triple)

    return relations
