from models.schemas import HeuristicResult


class HeuristicEngine:
    def analyze(self, requirement: str) -> HeuristicResult:
        text = requirement.lower()
        words = requirement.split()
        sentence_count = max(requirement.count("."), 1)

        complexity_score = 1.0
        complexity_score += min(len(words) / 40, 3.0)
        complexity_score += min(sentence_count / 5, 2.0)

        keywords = {
            "api": 0.5,
            "authentication": 1.0,
            "dashboard": 0.8,
            "integration": 1.2,
            "database": 1.0,
            "realtime": 1.5,
            "analytics": 1.1,
            "notification": 0.7,
            "upload": 0.6,
            "admin": 0.8,
        }

        detected_features: list[str] = []
        for keyword, weight in keywords.items():
            if keyword in text:
                detected_features.append(keyword)
                complexity_score += weight

        estimated_hours = round(max(4.0, complexity_score * 6), 1)

        return HeuristicResult(
            complexity_score=round(complexity_score, 2),
            detected_features=detected_features,
            estimated_hours=estimated_hours,
            rationale="Calculated from requirement length, sentence count, and weighted feature keywords.",
        )


heuristic_engine = HeuristicEngine()
