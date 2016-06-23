# Copyright (c) 2016 Hewlett-Packard Enterprise Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock

from searchlight.elasticsearch.plugins import base
from searchlight import listener
import searchlight.tests.utils as test_utils


class PretendNotificationHandler(base.NotificationBase):
    def __init__(self, *args, **kwargs):
        index_helper = mock.Mock()
        options = mock.Mock()
        super(PretendNotificationHandler, self).__init__(index_helper, options,
                                                         *args, **kwargs)
        self.event1_called_with = []

    @classmethod
    def _get_notification_exchanges(cls):
        return []

    def get_event_handlers(self):
        return {
            'test.create.end': self.event1
        }

    def event1(self, payload, timestamp):
        self.event1_called_with.append((payload, timestamp))


class StevedorePlugin(object):
    def __init__(self, name, plugin):
        self._plugin = plugin
        self._name = name

    @property
    def name(self):
        return self._name

    @property
    def obj(self):
        return self._plugin


class TestListener(test_utils.BaseTestCase):
    def test_multiple_event_handlers(self):
        handler1 = PretendNotificationHandler()
        plugin1 = mock.Mock()
        plugin1.get_notification_handler.return_value = handler1

        handler2 = PretendNotificationHandler()
        plugin2 = mock.Mock()
        plugin2.get_notification_handler.return_value = handler2

        plugins = {'plugin1': StevedorePlugin('plugin1', plugin1),
                   'plugin2': StevedorePlugin('plugin1', plugin2)}
        notification_ep = listener.NotificationEndpoint(plugins)

        self.assertEqual(['test.create.end'],
                         list(notification_ep.notification_target_map.keys()))
        self.assertEqual(
            set([plugin1, plugin2]),
            set(notification_ep.notification_target_map['test.create.end']))

        notification_ep.info({}, None, 'test.create.end',
                             {'test': 'payload'}, {'timestamp': 1234})

        self.assertEqual([({'test': 'payload'}, 1234)],
                         handler1.event1_called_with)
        self.assertEqual([({'test': 'payload'}, 1234)],
                         handler2.event1_called_with)
