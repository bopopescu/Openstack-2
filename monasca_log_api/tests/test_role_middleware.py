# Copyright 2015 FUJITSU LIMITED
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import unittest

import mock
from webob import response

from monasca_log_api.middleware import role_middleware as rm


class SideLogicTestEnsureLowerRoles(unittest.TestCase):
    def test_should_ensure_lower_roles(self):
        roles = ['CMM-Admin', '    CmM-User   ']
        expected = ['cmm-admin', 'cmm-user']
        self.assertItemsEqual(expected, rm._ensure_lower_roles(roles))

    def test_should_return_empty_array_for_falsy_input_1(self):
        roles = []
        expected = []
        self.assertItemsEqual(expected, rm._ensure_lower_roles(roles))

    def test_should_return_empty_array_for_falsy_input_2(self):
        roles = None
        expected = []
        self.assertItemsEqual(expected, rm._ensure_lower_roles(roles))


class SideLogicTestIntersect(unittest.TestCase):
    def test_should_intersect_seqs(self):
        seq_1 = [1, 2, 3]
        seq_2 = [2]

        expected = [2]

        self.assertItemsEqual(expected, rm._intersect(seq_1, seq_2))
        self.assertItemsEqual(expected, rm._intersect(seq_2, seq_1))

    def test_should_intersect_empty(self):
        seq_1 = []
        seq_2 = []

        expected = []

        self.assertItemsEqual(expected, rm._intersect(seq_1, seq_2))
        self.assertItemsEqual(expected, rm._intersect(seq_2, seq_1))

    def test_should_not_intersect_without_common_elements(self):
        seq_1 = [1, 2, 3]
        seq_2 = [4, 5, 6]

        expected = []

        self.assertItemsEqual(expected, rm._intersect(seq_1, seq_2))
        self.assertItemsEqual(expected, rm._intersect(seq_2, seq_1))


class RolesMiddlewareSideLogicTest(unittest.TestCase):
    def test_should_apply_middleware_for_valid_path(self):
        paths = ['/', '/v2.0/', '/v2.0/log/']

        instance = rm.RoleMiddleware(None)
        instance._path = paths

        for p in paths:
            req = mock.Mock()
            req.method = 'GET'
            req.path = p
            self.assertTrue(instance._can_apply_middleware(req))

    def test_should_apply_middleware_for_invalid_path(self):
        paths = ['/v2.0/', '/v2.0/log/']

        instance = rm.RoleMiddleware(None)
        instance._path = paths

        for p in paths:
            pp = 'test/%s' % p
            req = mock.Mock()
            req.method = 'GET'
            req.path = pp
            self.assertFalse(instance._can_apply_middleware(req))

    def test_should_reject_OPTIONS_request(self):
        instance = rm.RoleMiddleware(None)
        req = mock.Mock()
        req.method = 'OPTIONS'
        req.path = '/'
        self.assertFalse(instance._can_apply_middleware(req))

    def test_should_return_true_if_authenticated(self):
        instance = rm.RoleMiddleware(None)

        req = mock.Mock()
        req.headers = {rm._X_IDENTITY_STATUS: rm._CONFIRMED_STATUS}

        self.assertTrue(instance._is_authenticated(req))

    def test_should_return_false_if_not_authenticated(self):
        instance = rm.RoleMiddleware(None)

        req = mock.Mock()
        req.headers = {rm._X_IDENTITY_STATUS: 'Some_Other_Status'}

        self.assertFalse(instance._is_authenticated(req))

    def test_should_return_false_if_identity_status_not_found(self):
        instance = rm.RoleMiddleware(None)

        req = mock.Mock()
        req.headers = {}

        self.assertFalse(instance._is_authenticated(req))

    def test_should_return_true_if_authorized_no_agent(self):
        roles = 'cmm-admin,cmm-user'
        roles_array = roles.split(',')

        instance = rm.RoleMiddleware(None)
        instance._default_roles = roles_array
        instance._agent_roles = []

        req = mock.Mock()
        req.headers = {rm._X_ROLES: roles}

        is_authorized, is_agent = instance._is_authorized(req)

        self.assertFalse(is_agent)
        self.assertTrue(is_authorized)

    def test_should_return_true_if_authorized_with_agent(self):
        roles = 'cmm-admin,cmm-user'
        roles_array = roles.split(',')

        default_roles = [roles_array[0]]
        admin_roles = [roles_array[1]]

        instance = rm.RoleMiddleware(None)
        instance._default_roles = default_roles
        instance._agent_roles = admin_roles

        req = mock.Mock()
        req.headers = {rm._X_ROLES: roles}

        is_authorized, is_agent = instance._is_authorized(req)

        self.assertTrue(is_agent)
        self.assertTrue(is_authorized)

    def test_should_return_not_authorized_no_x_roles(self):
        roles = 'cmm-admin,cmm-user'
        roles_array = roles.split(',')

        default_roles = [roles_array[0]]
        admin_roles = [roles_array[1]]

        instance = rm.RoleMiddleware(None)
        instance._default_roles = default_roles
        instance._agent_roles = admin_roles

        req = mock.Mock()
        req.headers = {}

        is_authorized, is_agent = instance._is_authorized(req)

        self.assertFalse(is_agent)
        self.assertFalse(is_authorized)

    def test_should_return_authorized_if_at_least_agent_true(self):
        roles = 'cmm-admin,cmm-user'
        roles_array = roles.split(',')

        default_roles = ['different_role']
        admin_roles = [roles_array[1]]

        instance = rm.RoleMiddleware(None)
        instance._default_roles = default_roles
        instance._agent_roles = admin_roles

        req = mock.Mock()
        req.headers = {rm._X_ROLES: roles}

        is_authorized, is_agent = instance._is_authorized(req)

        self.assertTrue(is_agent)
        self.assertTrue(is_authorized)


class RolesMiddlewareLogicTest(unittest.TestCase):
    def test_not_process_further_if_cannot_apply_path(self):
        roles = 'cmm-admin,cmm-user'
        roles_array = roles.split(',')

        default_roles = [roles_array[0]]
        admin_roles = [roles_array[1]]

        instance = rm.RoleMiddleware(None)
        instance._default_roles = default_roles
        instance._agent_roles = admin_roles
        instance._path = ['/test']

        # spying
        instance._is_authenticated = mock.Mock()
        instance._is_authorized = mock.Mock()

        req = mock.Mock()
        req.headers = {rm._X_ROLES: roles}
        req.path = '/different/test'

        instance.process_request(req=req)

        self.assertFalse(instance._is_authenticated.called)
        self.assertFalse(instance._is_authorized.called)

    def test_not_process_further_if_cannot_apply_method(self):
        roles = 'cmm-admin,cmm-user'
        roles_array = roles.split(',')

        default_roles = [roles_array[0]]
        admin_roles = [roles_array[1]]

        instance = rm.RoleMiddleware(None)
        instance._default_roles = default_roles
        instance._agent_roles = admin_roles
        instance._path = ['/test']

        # spying
        instance._is_authenticated = mock.Mock()
        instance._is_authorized = mock.Mock()

        req = mock.Mock()
        req.headers = {rm._X_ROLES: roles}
        req.path = '/test'
        req.method = 'OPTIONS'

        instance.process_request(req=req)

        self.assertFalse(instance._is_authenticated.called)
        self.assertFalse(instance._is_authorized.called)

    def test_should_return_None_if_authenticated_authorized(self):
        instance = rm.RoleMiddleware(None)
        is_authorized = True
        is_agent = True

        instance._can_apply_middleware = mock.Mock(return_value=True)
        instance._is_authorized = mock.Mock(return_value=(is_authorized,
                                                          is_agent))
        instance._is_authenticated = mock.Mock(return_value=True)

        req = mock.Mock()
        req.environ = {}

        result = instance.process_request(req=req)

        self.assertIsNone(result)

    def test_should_produce_json_response_if_not_authorized_but_authenticated(
            self):
        instance = rm.RoleMiddleware(None)
        is_authorized = False
        is_agent = False
        is_authenticated = True

        instance._can_apply_middleware = mock.Mock(return_value=True)
        instance._is_authorized = mock.Mock(return_value=(is_authorized,
                                                          is_agent))
        instance._is_authenticated = mock.Mock(return_value=is_authenticated)

        req = mock.Mock()
        req.environ = {}
        req.headers = {
            'X-Tenant-Id': '11111111'
        }

        result = instance.process_request(req=req)

        self.assertIsNotNone(result)
        self.assertTrue(isinstance(result, response.Response))

        status = result.status_code
        json_body = result.json_body
        message = json_body.get('message')

        self.assertIn('is missing a required role to access', message)
        self.assertEqual(401, status)

    def test_should_produce_json_response_if_not_authenticated_but_authorized(
            self):
        instance = rm.RoleMiddleware(None)
        is_authorized = True
        is_agent = True
        is_authenticated = False

        instance._can_apply_middleware = mock.Mock(return_value=True)
        instance._is_authorized = mock.Mock(return_value=(is_authorized,
                                                          is_agent))
        instance._is_authenticated = mock.Mock(return_value=is_authenticated)

        req = mock.Mock()
        req.environ = {}
        req.headers = {
            'X-Tenant-Id': '11111111'
        }

        result = instance.process_request(req=req)

        self.assertIsNotNone(result)
        self.assertTrue(isinstance(result, response.Response))

        status = result.status_code
        json_body = result.json_body
        message = json_body.get('message')

        self.assertIn('Failed to authenticate request for', message)
        self.assertEqual(401, status)
