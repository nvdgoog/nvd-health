const bronzeTables = [
  "bronze_app_settings",
  "bronze_reacthealth_reports",
  "bronze_reacthealth_daily_usage",
  "google_user_sleeps",
  "google_user_sleep_scores",
  "google_user_sleep_stages",
  "google_user_exercises",
  "google_daily_resting_heart_rate",
  "google_daily_heart_rate_variability",
  "google_daily_oxygen_saturation",
  "google_daily_readiness",
  "google_daily_respiratory_rate",
  "google_daily_sleep_breathing_quality",
  "google_daily_sleep_temperature_derivations",
  "google_stress_score",
  "google_heart_rate",
  "google_body_temperature",
  "google_steps",
  "google_calories",
  "google_active_zone_minutes",
  "google_distance",
  "google_floors",
  "google_oxygen_saturation",
  "google_weight",
  "google_demographic_vo2max",
  "google_cardio_acute_chronic_workload_ratio",
  "transcend_cpap_daily_usage",
  "zenplanner_workouts"
];

bronzeTables.forEach((name) => {
  declare({
    database: dataform.projectConfig.defaultDatabase,
    schema: dataform.projectConfig.vars.bronze_dataset,
    name: name,
  });
});
