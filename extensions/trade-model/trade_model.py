"""The multi-sector trade model of Caliendo and Parro (2015), solved in relative changes.

Equation numbers are those of the article (Review of Economic Studies 82(1), pp. 10-12 and Appendix C,
pp. 31-32). A hat is the ratio of a variable after the shock to its value before; a prime marks the
value after the shock.

Index order, as in the article: the first country index is the importer.
    pi[n, i, j]        share of country n's spending on sector j that goes to goods from country i
    gamma_va[n, j]     share of value added in the output of sector j in country n
    gamma_io[n, k, j]  share of sector-k goods in the output of sector j in country n (gamma_n^{k,j})
    alpha[n, j]        share of sector j in country n's final spending
    tau[n, i, j]       ad valorem tariff of importer n on sector-j goods from i
    theta[j]           trade elasticity of sector j
    va[n]              value added (the model's labour income, w_n L_n)
    deficit[n]         trade deficit of country n; the deficits sum to zero
    X[n, j]            spending of country n on sector j, tariffs included

This file is the standard model only: every user of a sector's goods in a country buys the same mix of
origins. The variant with user-specific origin shares is trade_model_users.py (plan, step 4.1).

This file's own tests use made-up economies with known answers. The runs on FIGARO are in scenarios.py.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Economy:
    """A base-year equilibrium: shares, tariffs, elasticities and the values that go with them."""

    pi: np.ndarray
    gamma_va: np.ndarray
    gamma_io: np.ndarray
    alpha: np.ndarray
    tau: np.ndarray
    theta: np.ndarray
    va: np.ndarray
    deficit: np.ndarray
    X: np.ndarray

    @property
    def countries(self):
        return self.pi.shape[0]

    @property
    def sectors(self):
        return self.pi.shape[2]


@dataclass(frozen=True)
class Outcome:
    """The equilibrium after a shock, in changes and in values."""

    w_hat: np.ndarray           # wages, by country
    P_hat: np.ndarray           # sectoral price indices, [n, j]
    c_hat: np.ndarray           # unit costs of the input bundle, [n, j]
    pi: np.ndarray              # trade shares after the shock, [n, i, j]
    X: np.ndarray               # spending after the shock, [n, j]
    output: np.ndarray          # sales net of tariffs after the shock, [n, j]
    income: np.ndarray          # final absorption after the shock, by country
    revenue: np.ndarray         # tariff revenue after the shock, by country
    consumer_price_hat: np.ndarray
    real_wage_hat: np.ndarray
    welfare_hat: np.ndarray     # real final absorption: income change over consumer-price change
    iterations: int
    residual: float


def sales_shares(pi, tau):
    """S[n, k, i]: the part of importer i's spending on sector k that producers in n receive (tariffs taken out)."""
    return np.transpose(pi / (1.0 + tau), (1, 2, 0))


def revenue_rates(pi, tau):
    """r[n, j]: tariff revenue per unit of country n's spending on sector j."""
    return (tau * pi / (1.0 + tau)).sum(axis=1)


def output_of(pi, tau, X):
    """Sales net of tariffs, Y[n, k] = sum_i pi[i, n, k] / (1 + tau[i, n, k]) X[i, k]."""
    return np.einsum("nki,ik->nk", sales_shares(pi, tau), X)


def income_of(economy_or_va, deficit, pi, tau, X, w_hat=None):
    """Final absorption: labour income, tariff revenue and the deficit (equation 8)."""
    va = economy_or_va if w_hat is None else w_hat * economy_or_va
    revenue = (revenue_rates(pi, tau) * X).sum(axis=1)
    return va + revenue + deficit, revenue


def check_shapes(economy):
    N, J = economy.countries, economy.sectors
    expected = {"pi": (N, N, J), "gamma_va": (N, J), "gamma_io": (N, J, J), "alpha": (N, J), "tau": (N, N, J),
                "theta": (J,), "va": (N,), "deficit": (N,), "X": (N, J)}
    for name, shape in expected.items():
        if getattr(economy, name).shape != shape:
            raise ValueError(f"{name} has shape {getattr(economy, name).shape}, expected {shape}")


def base_residuals(economy):
    """How far the base year is from an equilibrium of the model, as the largest relative gap of each kind.

    The solver's no-shock test rests on these: shares that sum to one, goods-market clearing (equation 7),
    labour-market clearing (footnote 24) and deficits that sum to zero.
    """
    e = economy
    Y = output_of(e.pi, e.tau, e.X)
    income, _ = income_of(e.va, e.deficit, e.pi, e.tau, e.X)
    spending = np.einsum("njk,nk->nj", e.gamma_io, Y) + e.alpha * income[:, None]
    scale = e.X.sum()
    return {
        "trade_shares": float(np.abs(e.pi.sum(axis=1) - 1.0).max()),
        "input_shares": float(np.abs(e.gamma_io.sum(axis=1) + e.gamma_va - 1.0).max()),
        "final_shares": float(np.abs(e.alpha.sum(axis=1) - 1.0).max()),
        "goods_market": float(np.abs(spending - e.X).max() / scale),
        "labour_market": float(np.abs((e.gamma_va * Y).sum(axis=1) - e.va).max() / scale),
        "deficits": float(abs(e.deficit.sum()) / scale),
    }


def require_base(economy, tolerance=1e-8):
    check_shapes(economy)
    if (economy.gamma_va <= 0).any():
        raise ValueError("Every sector needs a positive value-added share: prices are not determined without one")
    if (economy.theta <= 0).any():
        raise ValueError("Trade elasticities must be positive")
    if (economy.pi < 0).any() or (economy.tau < 0).any():
        raise ValueError("Trade shares and tariffs must not be negative")
    worst = {name: gap for name, gap in base_residuals(economy).items() if gap > tolerance}
    if worst:
        raise ValueError(f"The base year is not an equilibrium of the model: {worst}")


def prices(economy, w_hat, kappa_hat, tolerance=1e-13, limit=10000):
    """Price indices and unit costs given wages: equations (10) and (11), iterated in logs.

    The iteration contracts because the input shares of every sector sum to less than one.
    """
    e = economy
    log_w = np.log(w_hat)
    log_P = np.zeros((e.countries, e.sectors))
    log_kappa = np.log(kappa_hat)
    with np.errstate(divide="ignore"):
        log_pi = np.where(e.pi > 0, np.log(np.where(e.pi > 0, e.pi, 1.0)), -np.inf)
    for _ in range(limit):
        log_c = e.gamma_va * log_w[:, None] + np.einsum("nkj,nk->nj", e.gamma_io, log_P)
        # exponent[n, i, j] = log pi - theta_j (log kappa[n, i, j] + log c[i, j])
        exponent = log_pi - e.theta[None, None, :] * (log_kappa + log_c[None, :, :])
        top = exponent.max(axis=1, keepdims=True)
        new = -(top[:, 0, :] + np.log(np.exp(exponent - top).sum(axis=1))) / e.theta[None, :]
        change = np.abs(new - log_P).max()
        log_P = new
        if change < tolerance:
            break
    else:
        raise RuntimeError("The price iteration did not converge")
    log_c = e.gamma_va * log_w[:, None] + np.einsum("nkj,nk->nj", e.gamma_io, log_P)
    return np.exp(log_P), np.exp(log_c)


def trade_shares(economy, P_hat, c_hat, kappa_hat):
    """Equation (12): pi' = pi (c_hat[i, j] kappa_hat[n, i, j] / P_hat[n, j]) ** (-theta[j])."""
    ratio = c_hat[None, :, :] * kappa_hat / P_hat[:, None, :]
    return economy.pi * ratio ** (-economy.theta[None, None, :])


def spending(economy, w_hat, pi_new, tau_new, deficit_new):
    """Equation (13), which is linear in spending given wages (Appendix C, equation C1)."""
    e = economy
    N, J = e.countries, e.sectors
    S = sales_shares(pi_new, tau_new)                                  # [n, k, i]
    A = np.einsum("njk,nki->njik", e.gamma_io, S)                      # inputs bought by n's sectors
    rates = revenue_rates(pi_new, tau_new)                             # [n, k]
    own = np.einsum("nj,nk->njk", e.alpha, rates)                      # tariff revenue spent at home
    A[np.arange(N), :, np.arange(N), :] += own
    b = e.alpha * (w_hat * e.va + deficit_new)[:, None]
    X = np.linalg.solve(np.eye(N * J) - A.reshape(N * J, N * J), b.reshape(N * J))
    return X.reshape(N, J)


def solve(economy, tau_new=None, iceberg_hat=None, deficit_new=None, damping=0.5, tolerance=1e-11, limit=5000,
          check_base=True, closure="labour"):
    """The equilibrium after a change of tariffs, of iceberg trade costs, of deficits, or of all three.

    Wages are found from labour-market clearing, which is equivalent to trade balance (equation 14) once
    spending solves equation (13). The numeraire is world value added, which keeps its base-year value.

    `check_base=False` skips the test that the base year is an equilibrium of the model, and
    `closure="trade_balance"` finds wages from trade balance instead of labour-market clearing. Both are for
    the article's own data: its input shares do not add up exactly, so its base year is an equilibrium only
    under the authors' own closure and only up to their tolerance.
    """
    if check_base:
        require_base(economy)
    else:
        check_shapes(economy)
    e = economy
    tau_new = e.tau if tau_new is None else np.asarray(tau_new, dtype=float)
    iceberg_hat = np.ones_like(e.pi) if iceberg_hat is None else np.asarray(iceberg_hat, dtype=float)
    deficit_new = e.deficit if deficit_new is None else np.asarray(deficit_new, dtype=float)
    if abs(deficit_new.sum()) > 1e-8 * e.X.sum():
        raise ValueError("Deficits must sum to zero")
    kappa_hat = iceberg_hat * (1.0 + tau_new) / (1.0 + e.tau)
    world = e.va.sum()

    if closure not in ("labour", "trade_balance"):
        raise ValueError(f"Unknown closure: {closure}")

    def at(wages):
        """Everything that follows from a wage vector, and the gap that moves each country's wage: the excess
        demand for its labour or, as in the authors' own programs, its exports plus its deficit minus its
        imports. Both are relative to its labour income, and they vanish together when the base year's
        accounts are exact (the article's footnote 24)."""
        P_hat, c_hat = prices(e, wages, kappa_hat)
        pi_new = trade_shares(e, P_hat, c_hat, kappa_hat)
        X_new = spending(e, wages, pi_new, tau_new, deficit_new)
        Y_new = output_of(pi_new, tau_new, X_new)
        if closure == "labour":
            gap = (e.gamma_va * Y_new).sum(axis=1) / (wages * e.va) - 1.0
        else:
            net = pi_new / (1.0 + tau_new) * X_new[:, None, :]
            gap = (net.sum(axis=(0, 2)) - net.sum(axis=(1, 2)) + deficit_new) / (wages * e.va)
        return gap, (P_hat, c_hat, pi_new, X_new, Y_new)

    # A wage rises where its labour is in excess demand. The step adapts: a step that makes the largest gap
    # worse is taken back and halved, a step that helps is lengthened a little. High trade elasticities make
    # demand respond strongly to wages, so the first step is short.
    w_hat = np.ones(e.countries)
    gap, state = at(w_hat)
    residual = float(np.abs(gap).max())
    step = min(damping, 1.0 / (1.0 + float(e.theta.max())))
    iteration = 0
    while residual >= tolerance:
        iteration += 1
        if iteration > limit or step < 1e-14:
            raise RuntimeError(f"Wages did not converge: residual {residual:.3e} after {iteration - 1} iterations")
        trial = w_hat * (1.0 + step * gap)
        trial = trial * world / (trial * e.va).sum()
        trial_gap, trial_state = at(trial)
        trial_residual = float(np.abs(trial_gap).max())
        if trial_residual < residual:
            w_hat, gap, state, residual = trial, trial_gap, trial_state, trial_residual
            step = min(1.0, step * 1.25)
        else:
            step *= 0.5
    P_hat, c_hat, pi_new, X_new, Y_new = state

    income_new, revenue_new = income_of(e.va, deficit_new, pi_new, tau_new, X_new, w_hat=w_hat)
    income_old, _ = income_of(e.va, e.deficit, e.pi, e.tau, e.X)
    consumer = np.exp((e.alpha * np.log(P_hat)).sum(axis=1))
    return Outcome(w_hat=w_hat, P_hat=P_hat, c_hat=c_hat, pi=pi_new, X=X_new, output=Y_new, income=income_new,
                   revenue=revenue_new, consumer_price_hat=consumer, real_wage_hat=w_hat / consumer,
                   welfare_hat=(income_new / income_old) / consumer, iterations=iteration, residual=residual)


def trade_balance_gap(economy, outcome, tau_new=None, deficit_new=None):
    """Equation (14) at the solution: imports minus the deficit minus exports, relative to world spending."""
    tau_new = economy.tau if tau_new is None else tau_new
    deficit_new = economy.deficit if deficit_new is None else deficit_new
    net = outcome.pi / (1.0 + tau_new) * outcome.X[:, None, :]          # [n, i, j]: n's payments to i
    imports = net.sum(axis=(1, 2))
    exports = net.sum(axis=(0, 2))
    return float(np.abs(imports - deficit_new - exports).max() / outcome.X.sum())


def base_from_shares(pi, gamma_va, gamma_io, alpha, tau, theta, deficit=None, world_spending=1000.0,
                     tolerance=1e-14, limit=200000):
    """A base-year equilibrium that fits given shares, tariffs and deficits: spending and value added follow.

    For made-up economies and toy examples. Spending solves equation (7) with labour income equal to the
    value added that the sales generate; the map preserves world spending, so it is iterated to its fixed point.
    """
    N, _, J = pi.shape
    deficit = np.zeros(N) if deficit is None else np.asarray(deficit, dtype=float)
    rates = revenue_rates(pi, tau)
    X = np.full((N, J), world_spending / (N * J))
    for _ in range(limit):
        Y = output_of(pi, tau, X)
        income = (gamma_va * Y).sum(axis=1) + (rates * X).sum(axis=1) + deficit
        new = np.einsum("njk,nk->nj", gamma_io, Y) + alpha * income[:, None]
        if (new <= 0).any():
            raise ValueError("These deficits are too large for the economy: spending would be negative")
        change = np.abs(new - X).max()
        X = new
        if change < tolerance * world_spending:
            break
    else:
        raise RuntimeError("The base year did not converge")
    va = (gamma_va * output_of(pi, tau, X)).sum(axis=1)
    return Economy(pi=pi, gamma_va=gamma_va, gamma_io=gamma_io, alpha=alpha, tau=tau, theta=np.asarray(theta, float),
                   va=va, deficit=deficit, X=X)
