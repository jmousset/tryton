# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

import hashlib
import unittest
from functools import partial

from proteus import Model, Wizard
from proteus import config as pconfig
from trytond.server_context import ServerContext, TEST_CONTEXT

from .test_tryton import backup_db_cache, drop_create, restore_db_cache

__all__ = ['activate_modules', 'set_user']


def _func_name(func):
    if isinstance(func, partial):
        return f'{func.func.__qualname__}(*{func.args}, **{func.keywords})'
    else:
        assert not hasattr(func, '__self__')
        return func.__qualname__


def activate_modules(modules, *setup, cache_file_name=None):
    """Activate modules, and the module features named among them.

    A feature is named by its token, <module>.<feature>; it is not an ir.module
    row, so the list is split and both are switched on before the single
    activate_upgrade.
    """
    if isinstance(modules, str):
        modules = [modules]
    cache_name = cache_file_name or '-'.join(modules)
    # When the caller imposes the cache name it no longer derives from the
    # module list, so two scenarios sharing that name but differing in their
    # features would restore each other's database. Derivation is untouched
    # when no feature is asked for, so no existing cache key moves.
    if cache_file_name and (features := [m for m in modules if '.' in m]):
        digest = hashlib.shake_128(
            '-'.join(sorted(features)).encode('utf8')).hexdigest(8)
        cache_name += f'--{digest}'
    if setup_name := '|'.join(_func_name(f) for f in setup):
        cache_name += f'--{setup_name}'
    if restore_db_cache(cache_name):
        return _get_config()
    drop_create()

    cfg = _get_config()
    Module = Model.get('ir.module')
    records = Module.find([
            ('name', 'in', modules),
            ])
    feature_names = set(modules) - {r.name for r in records}
    Feature = Model.get('ir.module.feature')
    features = Feature.find([
            ('name', 'in', list(feature_names)),
            ]) if feature_names else []
    assert len(features) == len(feature_names), (
        f"Not found: {', '.join(feature_names - {f.name for f in features})}")
    Module.click(records, 'activate')
    if features:
        Feature.click(features, 'activate')
    with ServerContext().set_context(**TEST_CONTEXT):
        Wizard('ir.module.activate_upgrade').execute('upgrade')
    # The models fetched above were built against the pool as it stood before
    # the upgrade, when only ir and res were loaded. Keeping them would hand
    # the caller a class that predates every module it just activated -- and
    # silently skip the extensions those modules add. The restored-from-cache
    # path never builds them, so without this the two paths disagree.
    Model.reset(cfg)

    for func in setup:
        func(config=cfg)

    backup_db_cache(cache_name)
    return cfg


def _get_config():
    return pconfig.set_trytond()


def set_user(user=1, config=None):
    if not config:
        config = pconfig.get_config()
    User = Model.get('res.user', config=config)
    config.user = int(user)
    config._context = User.get_preferences(True, {})


_dummy_test_case = unittest.TestCase()
_dummy_test_case.maxDiff = None


def __getattr__(name):
    return getattr(_dummy_test_case, name)
