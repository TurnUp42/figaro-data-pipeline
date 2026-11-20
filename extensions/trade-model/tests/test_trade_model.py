"""Tests of the standard Caliendo-Parro model on made-up economies with known answers.

Each test compares the solver with a result that can be derived by hand:
  * no shock gives no change, with tariffs and deficits in the base year;
  * the scale of the economy does not matter;
  * one sector without intermediate goods: the change in the real wage is the domestic share's change to the
    power -1/theta, and moving to autarky costs 1 - (domestic share) ** (1/theta);
  * several sectors without intermediates: the first term of the article's equation (15);
  * input-output links: the whole of equation (15);
  * two symmetric countries: prices and shares in closed form, and relative wages do not move;
  * tariffs from zero in one sector: real income is the real wage over one minus the revenue share;
  * at every solution, trade is balanced as equation (14) says and world value added keeps its value.
"""

from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import trade_model as tm  # noqa: E402


def random_shares(rng, N, J, intermediates=True, tariffs=0.0, home_bias=3.0):
    """Shares of a made-up economy; `tariffs` is the largest base-year tariff."""
    pi = rng.uniform(0.2, 1.0, (N, N, J))
    pi[np.arange(N), np.arange(N), :] *= home_bias
    pi /= pi.sum(axis=1, keepdims=True)
    if intermediates:
        gamma_va = rng.uniform(0.3, 0.7, (N, J))
        raw = rng.uniform(0.1, 1.0, (N, J, J))
        gamma_io = raw / raw.sum(axis=1, keepdims=True) * (1.0 - gamma_va)[:, None, :]
    else:
        gamma_va = np.ones((N, J))
        gamma_io = np.zeros((N, J, J))
    alpha = rng.uniform(0.2, 1.0, (N, J))
    alpha /= alpha.sum(axis=1, keepdims=True)
    tau = rng.uniform(0.0, tariffs, (N, N, J)) if tariffs else np.zeros((N, N, J))
    tau[np.arange(N), np.arange(N), :] = 0.0
    theta = rng.uniform(2.0, 9.0, J)
    return pi, gamma_va, gamma_io, alpha, tau, theta


def economy(seed=1, N=4, J=3, deficit=None, **options):
    rng = np.random.default_rng(seed)
    return tm.base_from_shares(*random_shares(rng, N, J, **options), deficit=deficit)


def bilateral(e, rng, low=0.0, high=0.3):
    """New tariffs on every pair of different countries."""
    tau = rng.uniform(low, high, e.tau.shape)
    tau[np.arange(e.countries), np.arange(e.countries), :] = 0.0
    return tau


def domestic(pi):
    return pi[np.arange(pi.shape[0]), np.arange(pi.shape[0]), :]


class TradeModelTest(unittest.TestCase):
    def assertClose(self, a, b, tolerance=1e-8, message=None):
        self.assertTrue(np.allclose(a, b, rtol=tolerance, atol=tolerance), message or f"{a}\n!=\n{b}")

    def test_the_made_up_base_year_is_an_equilibrium(self):
        for options in ({}, {"tariffs": 0.2}, {"intermediates": False}):
            e = economy(**options)
            self.assertLess(max(tm.base_residuals(e).values()), 1e-10, options)
            self.assertClose(e.X.sum(), 1000.0)
        deficit = np.array([20.0, -5.0, -15.0, 0.0])
        e = economy(tariffs=0.2, deficit=deficit)
        self.assertLess(max(tm.base_residuals(e).values()), 1e-10)
        # The deficit is what the country imports beyond what it exports (equation 9).
        net = e.pi / (1.0 + e.tau) * e.X[:, None, :]
        self.assertClose(net.sum(axis=(1, 2)) - net.sum(axis=(0, 2)), deficit, 1e-7)

    def test_no_shock_gives_no_change(self):
        e = economy(tariffs=0.25, deficit=np.array([10.0, -4.0, -6.0, 0.0]))
        out = tm.solve(e)
        self.assertClose(out.w_hat, 1.0)
        self.assertClose(out.P_hat, 1.0)
        self.assertClose(out.pi, e.pi)
        self.assertClose(out.X, e.X, 1e-7)
        self.assertClose(out.welfare_hat, 1.0)

    def test_a_base_year_that_is_no_equilibrium_is_refused(self):
        e = economy()
        broken = tm.Economy(**{**e.__dict__, "X": e.X * np.linspace(0.9, 1.1, e.X.size).reshape(e.X.shape)})
        with self.assertRaises(ValueError):
            tm.solve(broken)
        with self.assertRaises(ValueError):
            tm.solve(tm.Economy(**{**e.__dict__, "va": e.va[:-1]}))

    def test_the_scale_of_the_economy_does_not_matter(self):
        e = economy(tariffs=0.1, deficit=np.array([8.0, -8.0, 0.0, 0.0]))
        rng = np.random.default_rng(5)
        tau_new = bilateral(e, rng)
        big = tm.Economy(**{**e.__dict__, "va": e.va * 7.0, "X": e.X * 7.0, "deficit": e.deficit * 7.0})
        a, b = tm.solve(e, tau_new=tau_new), tm.solve(big, tau_new=tau_new)
        self.assertClose(a.w_hat, b.w_hat)
        self.assertClose(a.welfare_hat, b.welfare_hat)
        self.assertClose(a.X * 7.0, b.X, 1e-7)

    def test_one_sector_without_intermediates(self):
        # Real wage change = (change of the domestic share) ** (-1 / theta), for any change of trade costs.
        e = economy(seed=2, N=5, J=1, intermediates=False)
        rng = np.random.default_rng(7)
        iceberg = rng.uniform(0.7, 1.6, e.pi.shape)
        iceberg[np.arange(5), np.arange(5), :] = 1.0
        out = tm.solve(e, iceberg_hat=iceberg)
        change = domestic(out.pi)[:, 0] / domestic(e.pi)[:, 0]
        self.assertClose(out.real_wage_hat, change ** (-1.0 / e.theta[0]))
        self.assertClose(out.welfare_hat, out.real_wage_hat)       # no tariffs, no deficits: income is wages
        self.assertGreater(np.abs(out.w_hat - 1.0).max(), 1e-3)    # the shock did move something

    def test_moving_to_autarky(self):
        # With prohibitive trade costs the loss is 1 - (domestic share) ** (1 / theta).
        e = economy(seed=3, N=3, J=1, intermediates=False)
        iceberg = np.full(e.pi.shape, 1e6)
        iceberg[np.arange(3), np.arange(3), :] = 1.0
        out = tm.solve(e, iceberg_hat=iceberg)
        self.assertClose(out.welfare_hat, domestic(e.pi)[:, 0] ** (1.0 / e.theta[0]), 1e-7)
        self.assertClose(domestic(out.pi), 1.0, 1e-7)

    def test_several_sectors_without_intermediates(self):
        e = economy(seed=4, N=4, J=3, intermediates=False)
        rng = np.random.default_rng(11)
        iceberg = rng.uniform(0.8, 1.5, e.pi.shape)
        iceberg[np.arange(4), np.arange(4), :] = 1.0
        out = tm.solve(e, iceberg_hat=iceberg)
        change = np.log(domestic(out.pi) / domestic(e.pi))
        self.assertClose(np.log(out.real_wage_hat), -(e.alpha / e.theta[None, :] * change).sum(axis=1))

    def test_equation_15_with_input_output_links(self):
        # ln(w_hat / P_hat) = - sum_j alpha_j / theta_j ln(pi_hat_nn^j)
        #                     - sum_j alpha_j / theta_j (1 - gamma_j) / gamma_j ln(pi_hat_nn^j)
        #                     - sum_j alpha_j / gamma_j sum_k gamma^{k,j} ln(P_hat^k / P_hat^j)
        e = economy(seed=6, N=4, J=3, tariffs=0.15)
        rng = np.random.default_rng(13)
        out = tm.solve(e, tau_new=bilateral(e, rng))
        change = np.log(domestic(out.pi) / domestic(e.pi))
        logP = np.log(out.P_hat)
        final = -(e.alpha / e.theta[None, :] * change).sum(axis=1)
        intermediate = -(e.alpha / e.theta[None, :] * (1.0 - e.gamma_va) / e.gamma_va * change).sum(axis=1)
        relative = logP[:, :, None] - logP[:, None, :]                       # [n, k, j]: ln P^k - ln P^j
        linkages = -(e.alpha / e.gamma_va * (e.gamma_io * relative).sum(axis=1)).sum(axis=1)
        self.assertClose(np.log(out.real_wage_hat), final + intermediate + linkages)
        self.assertGreater(np.abs(linkages).max(), 1e-5)                     # the links matter in this example

    def test_two_symmetric_countries(self):
        # One sector, no intermediates, the same tariff t on both sides, starting from free trade:
        # wages do not move, P_hat = [d + (1 - d) (1 + t) ** -theta] ** (-1 / theta), and the domestic share
        # becomes d / [d + (1 - d) (1 + t) ** -theta].
        d, theta, t = 0.7, 5.0, 0.2
        pi = np.array([[[d], [1 - d]], [[1 - d], [d]]])
        e = tm.base_from_shares(pi, np.ones((2, 1)), np.zeros((2, 1, 1)), np.ones((2, 1)), np.zeros((2, 2, 1)), [theta])
        tau_new = np.array([[[0.0], [t]], [[t], [0.0]]])
        out = tm.solve(e, tau_new=tau_new)
        inside = d + (1 - d) * (1 + t) ** (-theta)
        self.assertClose(out.w_hat, 1.0)
        self.assertClose(out.P_hat, inside ** (-1.0 / theta))
        self.assertClose(domestic(out.pi), d / inside)
        # Revenue is t / (1 + t) of spending on imports, and it is spent: income = wages + revenue.
        imports = (1 - d / inside) * out.X[:, 0]
        self.assertClose(out.revenue, t / (1 + t) * imports)
        self.assertClose(out.income, e.va + out.revenue)

    def test_tariffs_from_zero_in_one_sector(self):
        # Real income = (domestic share's change) ** (-1 / theta) / (1 - revenue share of income).
        e = economy(seed=8, N=4, J=1, intermediates=False)
        rng = np.random.default_rng(17)
        out = tm.solve(e, tau_new=bilateral(e, rng, 0.05, 0.4))
        change = domestic(out.pi)[:, 0] / domestic(e.pi)[:, 0]
        share = out.revenue / out.income
        self.assertClose(out.welfare_hat, change ** (-1.0 / e.theta[0]) / (1.0 - share))
        self.assertTrue((out.revenue > 0).all())

    def test_trade_balance_and_numeraire_at_the_solution(self):
        deficit = np.array([12.0, -7.0, -5.0, 0.0])
        e = economy(seed=9, tariffs=0.2, deficit=deficit)
        rng = np.random.default_rng(19)
        tau_new = bilateral(e, rng)
        out = tm.solve(e, tau_new=tau_new)
        self.assertLess(tm.trade_balance_gap(e, out, tau_new=tau_new), 1e-9)
        self.assertClose((out.w_hat * e.va).sum(), e.va.sum())
        self.assertClose(out.X.sum(), out.output.sum() + out.revenue.sum(), 1e-7)   # spending = sales + tariffs
        self.assertClose(out.pi.sum(axis=1), 1.0)
        # Removing the deficits is a shock of its own, and leaves trade balanced.
        balanced = tm.solve(e, deficit_new=np.zeros(4))
        self.assertLess(tm.trade_balance_gap(e, balanced, deficit_new=np.zeros(4)), 1e-9)
        self.assertGreater(np.abs(balanced.w_hat - 1.0).max(), 1e-4)

    def test_a_larger_economy_solves(self):
        # Twelve countries and ten sectors with input-output links, a sector nobody trades, and zero trade shares.
        rng = np.random.default_rng(23)
        N, J = 12, 10
        pi, gamma_va, gamma_io, alpha, tau, theta = random_shares(rng, N, J, tariffs=0.1)
        pi[:, :, J - 1] = np.eye(N)                       # a non-traded sector
        pi[0, 1, 0] = 0.0                                 # a pair that does not trade in sector 0
        pi /= pi.sum(axis=1, keepdims=True)
        e = tm.base_from_shares(pi, gamma_va, gamma_io, alpha, tau, theta)
        tau_new = e.tau.copy()
        tau_new[0, 1:, :] += 0.25                          # country 0 raises its tariffs on everyone by 25 points
        tau_new[:, :, J - 1] = 0.0
        out = tm.solve(e, tau_new=tau_new)
        self.assertLess(out.residual, 1e-10)
        self.assertLess(tm.trade_balance_gap(e, out, tau_new=tau_new), 1e-9)
        self.assertEqual(out.pi[0, 1, 0], 0.0)
        self.assertClose(domestic(out.pi)[:, J - 1], 1.0)
        self.assertTrue((domestic(out.pi)[0, :J - 1] > domestic(e.pi)[0, :J - 1]).all())   # country 0 buys more at home


if __name__ == "__main__":
    unittest.main()
