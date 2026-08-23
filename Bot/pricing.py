
from __future__ import annotations


def prix_max_achat(prix_median_marche: float) -> float:
    """prix_max_achat = prix_median_marché / 2.5"""
    return round(prix_median_marche / 2.5, 2)


def compute_rentability(
    prix_achat: float,
    prix_median_marche: float,
    rotation_days: int = 10,
    min_margin_pct: float = 120,
    max_rotation_days: int = 14,
) -> dict:
    """
    marge_brute = (prix_vente_estimé - prix_achat) / prix_achat × 100
    rentable si marge_brute >= 120% ET rotation <= 14j
    Sortie : score de rentabilité 0-100 + recommandation ACHETER/PASSER
    """
    prix_vente_estime = prix_median_marche  # hypothèse : revente au médian marché

    if prix_achat <= 0:
        return {
            "prix_vente_estime": round(prix_vente_estime, 2),
            "marge_brute_pct": 0.0,
            "rentable": False,
            "score": 0,
            "recommendation": "PASSER",
        }

    marge_brute_pct = ((prix_vente_estime - prix_achat) / prix_achat) * 100
    rentable = marge_brute_pct >= min_margin_pct and rotation_days <= max_rotation_days

    # Score 0-100 : 60 points pour la marge (au-delà du seuil mini),
    # 40 points pour la vitesse de rotation (plus c'est rapide, mieux c'est).
    margin_score = min(60.0, max(0.0, (marge_brute_pct / min_margin_pct) * 60))
    rotation_score = min(40.0, max(0.0, ((max_rotation_days - rotation_days) / max_rotation_days) * 40))
    score = round(min(100, margin_score + rotation_score))

    return {
        "prix_vente_estime": round(prix_vente_estime, 2),
        "marge_brute_pct": round(marge_brute_pct, 1),
        "rentable": rentable,
        "score": score,
        "recommendation": "ACHETER" if rentable else "PASSER",
    }


def suggested_offer(prix_affiche: float, offer_pct: float = 0.85) -> float:
    """Montant suggéré pour une offre (F3) — à valider et envoyer manuellement
    par l'utilisateur, le bot ne l'envoie jamais lui-même."""
    return round(prix_affiche * offer_pct, 2)
  
