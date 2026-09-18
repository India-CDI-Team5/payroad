"""
train_model.py
--------------
Pure Python Multiple Linear Regression model for surge prediction.
Uses enriched data with weather features for improved accuracy.
No external dependencies required (csv, json, math, random only).

Features: demand, supply, distance, hour, temperature, rain, wind
Target:   surge (supply-demand coefficient alpha)
"""
import csv
import json
import random
import math
import os


def load_data(filename):
    """Load enriched CSV data and prepare feature matrix and target vector."""
    X = []
    y = []

    # Check which file format we have (enriched or basic)
    with open(filename, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        has_weather = "TEMPERATURE" in headers

        for row in reader:
            try:
                demand = float(row["DEMAND_IN_RADIUS"])
                supply = float(row["SUPPLY_IN_RADIUS"])
                dist = float(row["PICKUP_DISTANCE_KM"])
                surge = float(row["SURGE"])

                if has_weather:
                    hour = float(row["HOUR"])
                    temp = float(row["TEMPERATURE"])
                    rain = float(row["RAIN"])
                    wind = float(row["WIND"])
                    # Features: [bias, demand, supply, distance, hour, temp, rain, wind]
                    X.append([1.0, demand, supply, dist, hour, temp, rain, wind])
                else:
                    # Fallback: basic features only
                    X.append([1.0, demand, supply, dist])

                y.append(surge)
            except (ValueError, KeyError):
                continue

    return X, y, has_weather


def normalize_features(X):
    """Min-Max normalization for stable gradient descent convergence."""
    n_features = len(X[0])
    mins = [float("inf")] * n_features
    maxs = [float("-inf")] * n_features

    for row in X:
        for j in range(n_features):
            if row[j] < mins[j]:
                mins[j] = row[j]
            if row[j] > maxs[j]:
                maxs[j] = row[j]

    # Keep bias column (index 0) unchanged
    mins[0] = 0.0
    maxs[0] = 1.0

    X_norm = []
    for row in X:
        norm_row = []
        for j in range(n_features):
            rng = maxs[j] - mins[j]
            if rng == 0:
                norm_row.append(0.0)
            else:
                norm_row.append((row[j] - mins[j]) / rng)
        X_norm.append(norm_row)

    return X_norm, mins, maxs


def train_linear_regression(X, y, epochs=5000, lr=0.01):
    """Gradient Descent training with feature normalization."""
    n_features = len(X[0])
    weights = [0.0] * n_features
    n_samples = len(X)

    for epoch in range(epochs):
        errors = []
        for i in range(n_samples):
            pred = sum(X[i][j] * weights[j] for j in range(n_features))
            error = pred - y[i]
            errors.append(error)

            for j in range(n_features):
                weights[j] -= lr * error * X[i][j] / n_samples

        if (epoch + 1) % 500 == 0:
            mse = sum(e ** 2 for e in errors) / n_samples
            rmse = math.sqrt(mse)
            print(f"  Epoch {epoch+1}/{epochs} - RMSE: {rmse:.4f}")

    return weights


def calculate_metrics(X, y, weights):
    """Calculate RMSE and MAE on a dataset."""
    n_samples = len(X)
    sq_errors = []
    abs_errors = []
    for i in range(n_samples):
        pred = sum(X[i][j] * weights[j] for j in range(len(weights)))
        sq_errors.append((pred - y[i]) ** 2)
        abs_errors.append(abs(pred - y[i]))

    rmse = math.sqrt(sum(sq_errors) / n_samples)
    mae = sum(abs_errors) / n_samples
    return rmse, mae


if __name__ == "__main__":
    # Try enriched data first, fall back to basic
    if os.path.exists("match_result_enriched.csv"):
        data_file = "match_result_enriched.csv"
    else:
        data_file = "match_result.csv"

    print(f"Loading data from {data_file}...")
    X, y, has_weather = load_data(data_file)
    print(f"Total {len(X)} records loaded.")

    if has_weather:
        feature_names = [
            "bias", "demand_in_radius", "supply_in_radius",
            "pickup_distance_km", "hour", "temperature", "rain", "wind"
        ]
        print("Using ENRICHED features (with weather data)")
    else:
        feature_names = [
            "bias", "demand_in_radius", "supply_in_radius",
            "pickup_distance_km"
        ]
        print("Using BASIC features (no weather data)")

    # Normalize features for stable training
    X_norm, mins, maxs = normalize_features(X)

    # Train/Test split (80/20)
    combined = list(zip(X_norm, y))
    random.seed(42)
    random.shuffle(combined)
    split_idx = int(len(combined) * 0.8)

    train_data = combined[:split_idx]
    test_data = combined[split_idx:]

    X_train = [item[0] for item in train_data]
    y_train = [item[1] for item in train_data]
    X_test = [item[0] for item in test_data]
    y_test = [item[1] for item in test_data]

    print(f"\nTrain: {len(X_train)} records, Test: {len(X_test)} records")
    print("Starting model training...\n")

    model_weights = train_linear_regression(X_train, y_train, epochs=3000, lr=0.05)

    # Evaluate
    train_rmse, train_mae = calculate_metrics(X_train, y_train, model_weights)
    test_rmse, test_mae = calculate_metrics(X_test, y_test, model_weights)

    print(f"\n--- Results ---")
    print(f"Train - RMSE: {train_rmse:.4f}, MAE: {train_mae:.4f}")
    print(f"Test  - RMSE: {test_rmse:.4f}, MAE: {test_mae:.4f}")

    # Save model (weights + normalization params for inference)
    model_path = "surge_model.json"
    model_data = {
        "weights": model_weights,
        "features": feature_names,
        "normalization": {
            "mins": mins,
            "maxs": maxs
        }
    }

    with open(model_path, "w", encoding="utf-8") as f:
        json.dump(model_data, f, indent=4)

    print(f"\nModel saved to {model_path}.")
