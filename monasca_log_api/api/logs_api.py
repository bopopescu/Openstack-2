# Copyright 2015 kornicameister@gmail.com
# Copyright 2016 FUJITSU LIMITED
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

import falcon
from oslo_log import log

LOG = log.getLogger(__name__)

MONITORING_DELEGATE_ROLE = 'monitoring-delegate'


class LogsApi(object):
    """Logs API.

    Logs API acts as RESTful endpoint accepting
    messages contains collected log entries from the system.
    Works as gateway for any further processing for accepted data.

    """
    def __init__(self):
        super(LogsApi, self).__init__()
        LOG.info('Initializing LogsApi %s!' % self.version)

    def on_post(self, req, res):
        """Accepts sent logs as text or json.

        Accepts logs sent to resource which should
        be sent to kafka queue.

        :param req: current request
        :param res: current response

        """
        res.status = falcon.HTTP_501  # pragma: no cover

    @property
    def version(self):
        return getattr(self, 'VERSION')
