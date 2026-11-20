"""Bound a declared multivariate first-harmonic trigonometric load model.

Angles at the public interface are degrees; derivatives and cell radii use
radians. Bounds use floating-point analytical inequalities with explicit
padding. They are not a formally directed-rounding interval certificate.
"""

import heapq
import itertools
import math
import sys


def _finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(label + " must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(label + " must be a finite number")
    return value


def build_trig_model(evaluate, dimensions):
    """Recover coefficients of products of 1, cos(q), and sin(q).

    The caller must establish first-harmonic dependence in each coordinate.
    Independent off-grid reconstruction checks detect common contract errors;
    finite checks alone cannot prove that arbitrary functions have this form.
    """
    if type(dimensions) is not int or not 1 <= dimensions <= 6:
        raise ValueError("dimensions must be an integer from one to six")
    keys = list(itertools.product(range(3), repeat=dimensions))
    samples = {
        key: _finite(evaluate([90.0 * index for index in key]), "load")
        for key in keys
    }
    coefficients = dict(samples)
    for axis in range(dimensions):
        transformed = {}
        for rest in itertools.product(range(3), repeat=dimensions - 1):
            indices = [rest[:axis] + (index,) + rest[axis:] for index in range(3)]
            zero, quarter, half = [coefficients[index] for index in indices]
            constant = (zero + half) / 2.0
            for index, value in zip(indices, (constant, (zero - half) / 2.0, quarter - constant)):
                transformed[index] = value
        coefficients = transformed
    scale = max(1.0, max(abs(value) for value in samples.values()))
    threshold = scale * 1e-12
    dropped = math.fsum(abs(value) for value in coefficients.values() if abs(value) <= threshold)
    terms = [
        (tuple((axis, power) for axis, power in enumerate(powers) if power), value)
        for powers, value in coefficients.items()
        if abs(value) > threshold
    ]
    # This is a disclosed floating-point allowance, not a proof of libm error.
    roundoff = 256.0 * sys.float_info.epsilon * scale * len(keys)
    error = math.nextafter(dropped + roundoff, math.inf)
    first = [math.fsum(abs(value) for active, value in terms if any(i == axis for i, _ in active))
             for axis in range(dimensions)]
    hessian = [[
        math.fsum(abs(value) for active, value in terms
                  if any(i == row for i, _ in active) and any(i == column for i, _ in active))
        for column in range(dimensions)
    ] for row in range(dimensions)]
    model = {
        "dimensions": dimensions,
        "terms": terms,
        "coefficient_error_bound": dropped,
        "floating_error_padding": roundoff,
        "model_error_bound": error,
        "first_derivative_abs_bounds": first,
        "hessian_abs_bounds": hessian,
        "tensor_evaluations": len(keys),
        "reconstruction_validation_evaluations": 9,
        "first_harmonic_contract": "caller_derived_with_independent_numerical_checks",
    }
    residual = 0.0
    for sample in range(9):
        angles = [((sample + 1) * (axis + 2) * 47.137 + axis * 19.31) % 360.0 - 180.0
                  for axis in range(dimensions)]
        observed = _finite(evaluate(angles), "validation load")
        predicted = _value(model, [math.radians(value) for value in angles])
        residual = max(residual, abs(observed - predicted))
        if abs(observed - predicted) > 1e-8 * max(scale, abs(observed), 1.0):
            raise ValueError("load does not satisfy the declared first-harmonic model")
    model["maximum_reconstruction_residual"] = residual
    # Include the observed numerical residual without calling it a global proof.
    model["model_error_bound"] = math.nextafter(error + residual, math.inf)
    return model


def _basis(angles):
    return [(1.0, math.cos(value), math.sin(value)) for value in angles]


def _value(model, angles):
    basis = _basis(angles)
    values = []
    for active, coefficient in model["terms"]:
        term = coefficient
        for axis, power in active:
            term *= basis[axis][power]
        values.append(term)
    return math.fsum(values)


def _value_gradient(model, angles):
    basis = _basis(angles)
    value_terms = []
    gradient_terms = [[] for _ in angles]
    for active, coefficient in model["terms"]:
        factors = [basis[axis][power] for axis, power in active]
        prefix = [coefficient]
        for factor in factors:
            prefix.append(prefix[-1] * factor)
        suffix = 1.0
        for index in range(len(active) - 1, -1, -1):
            axis, power = active[index]
            derivative = -basis[axis][2] if power == 1 else basis[axis][1]
            gradient_terms[axis].append(prefix[index] * derivative * suffix)
            suffix *= factors[index]
        value_terms.append(prefix[-1])
    return math.fsum(value_terms), [math.fsum(values) for values in gradient_terms]


def _trig_range(low, high, power):
    if high - low >= 2.0 * math.pi:
        return (-1.0, 1.0)
    offset = 0.0 if power == 1 else math.pi / 2.0
    function = math.cos if power == 1 else math.sin
    values = [function(low), function(high)]
    start = math.ceil((low - offset) / math.pi)
    stop = math.floor((high - offset) / math.pi)
    for multiple in range(start, stop + 1):
        values.append(1.0 if multiple % 2 == 0 else -1.0)
    return (math.nextafter(min(values), -math.inf), math.nextafter(max(values), math.inf))


def _natural_interval(model, bounds):
    intervals = [[(1.0, 1.0), _trig_range(low, high, 1), _trig_range(low, high, 2)]
                 for low, high in bounds]
    lower_terms, upper_terms = [], []
    for active, coefficient in model["terms"]:
        low = high = coefficient
        for axis, power in active:
            other_low, other_high = intervals[axis][power]
            products = (low * other_low, low * other_high, high * other_low, high * other_high)
            low, high = min(products), max(products)
        lower_terms.append(low)
        upper_terms.append(high)
    return max(abs(math.fsum(lower_terms)), abs(math.fsum(upper_terms)))


def _cell_bound(model, bounds):
    center = [(low + high) / 2.0 for low, high in bounds]
    radii = [(high - low) / 2.0 for low, high in bounds]
    value, gradient = _value_gradient(model, center)
    hessian = model["hessian_abs_bounds"]
    remainder = 0.5 * math.fsum(hessian[row][column] * radii[row] * radii[column]
                               for row in range(len(bounds)) for column in range(len(bounds)))
    taylor = abs(value) + math.fsum(abs(g) * h for g, h in zip(gradient, radii)) + remainder
    bound = min(taylor, _natural_interval(model, bounds))
    # Protect the bound from ordinary accumulated arithmetic roundoff. The
    # status returned to the caller still explicitly excludes formal intervals.
    padding = model["model_error_bound"] + 64.0 * sys.float_info.epsilon * max(1.0, bound)
    upper = math.nextafter(bound + padding, math.inf)
    priorities = [radii[row] * (abs(gradient[row]) + math.fsum(hessian[row][column] * radii[column]
                                                           for column in range(len(bounds))))
                  for row in range(len(bounds))]
    return upper, center, value, priorities


def _coordinate_witness(model, bounds, start):
    point = list(start)
    value = _value(model, point)
    for _ in range(12):
        previous = abs(value)
        for axis, (low, high) in enumerate(bounds):
            basis = _basis(point)
            coefficients = [[], [], []]
            for active, coefficient in model["terms"]:
                power_here = 0
                term = coefficient
                for index, power in active:
                    if index == axis:
                        power_here = power
                    else:
                        term *= basis[index][power]
                coefficients[power_here].append(term)
            constant, cosine, sine = [math.fsum(values) for values in coefficients]
            candidates = [point[axis], low, high]
            if cosine or sine:
                phase = math.atan2(sine, cosine)
                first = math.ceil((low - phase) / math.pi)
                last = math.floor((high - phase) / math.pi)
                candidates.extend(phase + multiple * math.pi for multiple in range(first, last + 1))
            best_angle, best_value = point[axis], value
            for angle in candidates:
                candidate = constant + cosine * math.cos(angle) + sine * math.sin(angle)
                if abs(candidate) > abs(best_value):
                    best_angle, best_value = angle, candidate
            point[axis] = best_angle
            # Re-evaluation avoids retaining a different summation's rounding.
            value = _value(model, point)
        if abs(value) - previous <= 1e-13 * max(1.0, abs(value)):
            break
    return point, value


def maximize_absolute(model, bounds_deg, seeds_deg=None, tolerance=0.01, max_cells=12000):
    """Enclose the maximum absolute load over the complete declared joint box.

    Coordinate ascent supplies feasible witnesses. Branch and bound covers the
    whole box; a resource cap returns the remaining gap instead of an optimum
    claim. The tolerance is absolute in the evaluated function's load unit.
    """
    dimensions = model["dimensions"]
    if len(bounds_deg) != dimensions:
        raise ValueError("one bound pair per dimension is required")
    bounds = []
    for pair in bounds_deg:
        if len(pair) != 2:
            raise ValueError("bounds must contain two finite angles")
        low, high = [_finite(value, "bound") for value in pair]
        if low > high:
            raise ValueError("lower bound exceeds upper bound")
        bounds.append((math.radians(low), math.radians(high)))
    tolerance = _finite(tolerance, "tolerance")
    if tolerance <= 0:
        raise ValueError("tolerance must be positive")
    if type(max_cells) is not int or max_cells < 1:
        raise ValueError("max_cells must be a positive integer")
    seeds = [list(values) for values in itertools.product(*[(low, high) for low, high in bounds])]
    seeds.extend([[(low + high) / 2.0 for low, high in bounds],
                  [min(high, max(low, 0.0)) for low, high in bounds]])
    if seeds_deg is not None:
        for seed in seeds_deg:
            if len(seed) != dimensions:
                raise ValueError("seed dimension mismatch")
            values = [math.radians(_finite(value, "seed")) for value in seed]
            if any(not low <= value <= high for value, (low, high) in zip(values, bounds)):
                raise ValueError("seed lies outside bounds")
            seeds.append(values)
    witness, signed_value = seeds[0], _value(model, seeds[0])
    for seed in seeds:
        candidate, value = _coordinate_witness(model, bounds, seed)
        if abs(value) > abs(signed_value):
            witness, signed_value = candidate, value
    error = model["model_error_bound"]
    lower = max(0.0, abs(signed_value) - error)
    initial_upper, center, center_value, priorities = _cell_bound(model, bounds)
    if abs(center_value) > abs(signed_value):
        witness, signed_value = center, center_value
        lower = max(0.0, abs(signed_value) - error)
    counter = 0
    heap = [(-initial_upper, counter, bounds, priorities)]
    evaluated = 1
    while heap and -heap[0][0] - lower > tolerance and evaluated + 2 <= max_cells:
        negative_upper, _, cell, priorities = heapq.heappop(heap)
        if -negative_upper <= lower:
            continue
        axis = max(range(dimensions), key=lambda index: (priorities[index], cell[index][1] - cell[index][0], -index))
        low, high = cell[axis]
        middle = (low + high) / 2.0
        if middle == low or middle == high:
            # Floating resolution prevents subdivision; preserve its bound.
            heapq.heappush(heap, (negative_upper, counter, cell, priorities))
            break
        for replacement in ((low, middle), (middle, high)):
            child = list(cell)
            child[axis] = replacement
            upper, center, value, priorities_child = _cell_bound(model, child)
            evaluated += 1
            if abs(value) > abs(signed_value):
                witness, signed_value = center, value
                lower = max(0.0, abs(signed_value) - error)
            if upper >= lower:
                counter += 1
                heapq.heappush(heap, (-upper, counter, child, priorities_child))
    upper = max(lower, -heap[0][0] if heap else lower)
    gap = max(0.0, upper - lower)
    return {
        "lower_bound": lower,
        "upper_bound": upper,
        "witness_deg": [math.degrees(value) for value in witness],
        "witness_value": signed_value,
        "gap": gap,
        "converged": gap <= tolerance,
        "evaluated_cells": evaluated,
        "method": "exact_coordinate_witnesses_and_whole_box_taylor_trigonometric_branch_and_bound",
        "bound_status": "floating_analytical_enclosure_not_formal_interval_certificate",
        "model_error_bound": error,
        "stopping_reason": "tolerance" if gap <= tolerance else "cell_or_floating_resolution_limit",
    }
