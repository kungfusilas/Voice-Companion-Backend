/**
 * Client-side mirror of the stage threshold logic in app/scoring.py.
 * Used to initialize the ConnectionMeter before the first API reply arrives.
 */

const STAGE_THRESHOLDS: Record<string, Array<[number, number, string]>> = {
  romance: [
    [0, 20, "Strangers"],
    [21, 40, "Noticed"],
    [41, 60, "Flirting"],
    [61, 80, "Crushing"],
    [81, 95, "Dating"],
    [96, 100, "Devoted"],
  ],
  mentor: [
    [0, 20, "Skeptical"],
    [21, 40, "Open"],
    [41, 60, "Engaged"],
    [61, 80, "Trusted"],
    [81, 100, "Transformed"],
  ],
  friendship: [
    [0, 20, "Acquaintance"],
    [21, 40, "Comfortable"],
    [41, 60, "Close"],
    [61, 80, "Best Friends"],
    [81, 100, "Ride or Die"],
  ],
  professional: [
    [0, 20, "Distant"],
    [21, 40, "Cordial"],
    [41, 60, "Reliable"],
    [61, 80, "Valued"],
    [81, 100, "Indispensable"],
  ],
};

function getStage(score: number, relType: string): [string, number, number] {
  const thresholds = STAGE_THRESHOLDS[relType] ?? STAGE_THRESHOLDS.romance;
  for (const [lo, hi, name] of thresholds) {
    if (score >= lo && score <= hi) return [name, lo, hi];
  }
  const last = thresholds[thresholds.length - 1];
  return [last[2], last[0], last[1]];
}

export const scoring = { getStage };
