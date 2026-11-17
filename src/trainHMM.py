import json
import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM


def build_features(df: pd.DataFrame, vol_window: int = 12) -> tuple[np.ndarray, pd.Index]:
    """
    Engineers a clean 2D regime feature vector from OHLCV bars:
      Feature 0: Absolute log return |ln(C_t / C_{t-1})| (directional energy)
      Feature 1: Rolling realized volatility of log returns (regime expansion vs. compression)
    """
    log_ret = np.log(df["close"] / df["close"].shift(1)) * 100.0
    abs_ret = log_ret.abs()
    realized_vol = log_ret.rolling(vol_window).std(ddof=0)

    feat_df = pd.DataFrame({
        "abs_ret": abs_ret,
        "realized_vol": realized_vol
    }).dropna()

    return feat_df.values, feat_df.index


def causal_forward_filter(
    observations: np.ndarray,
    pi: np.ndarray,
    A: np.ndarray,
    means: np.ndarray,
    covs: np.ndarray
) -> np.ndarray:
    """
    Zero-lookahead Bayesian Forward Filter for a K-state Gaussian HMM.
    Computes P(State_t = j | x_{1:t}) strictly using past & current closed bars.
    """
    T, D = observations.shape
    K = len(pi)
    posteriors = np.zeros((T, K))

    inv_covs = [np.linalg.inv(covs[j]) for j in range(K)]
    norm_consts = [
        1.0 / np.sqrt(((2.0 * np.pi) ** D) * np.linalg.det(covs[j]))
        for j in range(K)
    ]

    alpha = pi.copy()

    for t in range(T):
        # 1. Predict step (propagate prior belief through transition matrix A)
        if t > 0:
            alpha = alpha @ A

        # 2. Emission likelihood b_j(x_t) = N(x_t | mu_j, Sigma_j)
        x = observations[t]
        likelihoods = np.zeros(K)
        for j in range(K):
            diff = x - means[j]
            exponent = -0.5 * (diff @ inv_covs[j] @ diff)
            likelihoods[j] = norm_consts[j] * np.exp(exponent)

        # 3. Update & Normalize
        unnorm = alpha * likelihoods
        c_t = np.sum(unnorm)
        alpha = unnorm / (c_t + 1e-16)
        posteriors[t] = alpha

    return posteriors


def train_and_evaluate_hmm(
    csv_path: str,
    train_ratio: float = 0.70,
    vol_window: int = 12,
    trend_threshold: float = 0.65,
    export_json_path: str = "hmm_params.json"
):
    # 1. Load historical OHLCV CSV (expects columns: timestamp/time, open, high, low, close)
    df = pd.read_csv(csv_path)
    df.columns = [c.strip().lower() for c in df.columns]

    # 2. Build 2D feature matrix
    X, valid_idx = build_features(df, vol_window=vol_window)
    df_aligned = df.loc[valid_idx].reset_index(drop=True)

    # 3. Strict Walk-Forward Split (No In-Sample Leakage)
    split_idx = int(len(X) * train_ratio)
    X_train = X[:split_idx]
    X_test = X[split_idx:]
    df_test = df_aligned.iloc[split_idx:].reset_index(drop=True)

    # 4. Fit 2-State Gaussian HMM via Baum-Welch (EM) ONLY on Training Split
    model = GaussianHMM(
        n_components=3,
        covariance_type="full",
        min_covar=1e-4,
        n_iter=300,
        tol=1e-5,
        random_state=42
    )
    model.fit(X_train)

    # 5. Automatically Sort 3 States by Volatility (Low -> Medium -> High)
    # Higher mean realized volatility (feature index 1) = Trend/Expansion state
    state_vols = model.means_[:, 1]
    sorted_states = np.argsort(state_vols)

    chop_state  = int(sorted_states[0])
    trend_state = int(sorted_states[1])
    spike_state = int(sorted_states[2])
    print("=== LEARNED 3-STATE HMM PARAMETERS (IN-SAMPLE) ===")
    for name, idx in [("Chop ", chop_state), ("Trend", trend_state), ("Spike", spike_state)]:
        print(f"{name} State ({idx}): mean_abs_ret={model.means_[idx, 0]:.6f}, "
            f"mean_vol={model.means_[idx, 1]:.6f}, "
            f"stay_prob={model.transmat_[idx, idx]:.3f}")

    # 6. Export Frozen Parameters for Live MT5 Execution
    params_payload = {
        "vol_window": vol_window,
        "chop_state": chop_state,
        "trend_state": trend_state,
        "spike_state": spike_state,
        "trend_threshold": trend_threshold,
        "pi": model.startprob_.tolist(),
        "A": model.transmat_.tolist(),
        "means": model.means_.tolist(),
        "covs": model.covars_.tolist()
    }
    with open(export_json_path, "w") as f:
        json.dump(params_payload, f, indent=2)
    print(f"Saved frozen HMM parameters to: {export_json_path}")

    # 7. Run Zero-Lookahead Causal Forward Filter on Out-of-Sample Split
    oos_posteriors = causal_forward_filter(
        observations=X_test,
        pi=model.startprob_,
        A=model.transmat_,
        means=model.means_,
        covs=model.covars_
    )

    df_test["p_chop"] = oos_posteriors[:, chop_state]
    df_test["p_trend"] = oos_posteriors[:, trend_state]
    df_test["p_spike"] = oos_posteriors[:, spike_state]

    df_test["allow_breakout"] = df_test["p_trend"] + df_test["p_spike"] >= trend_threshold

    pct_allowed = df_test["allow_breakout"].mean() * 100.0
    print(f"\n=== OUT-OF-SAMPLE FORWARD FILTER SUMMARY ({len(df_test)} bars) ===")
    print(f"Bars passing P(Trend) >= {trend_threshold:.2f}: {pct_allowed:.1f}% "
          f"(Filtered out {100.0 - pct_allowed:.1f}% chop bars)")

    return df_test, params_payload


if __name__ == "__main__":
    # Replace with your actual M5 or M15 CSV path
    oos_df, params = train_and_evaluate_hmm(
        csv_path="history_data.csv",
        train_ratio=0.70,
        vol_window=4,         # 12 bars = 1 hour on M5 (use 4 for M15)
        trend_threshold=0.65,
        export_json_path="hmm_params.json"
    )
    print(oos_df[["close", "p_chop", "p_trend", "allow_breakout"]].tail(10))