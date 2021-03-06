# Copyright 2011 Justin Santa Barbara
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""The volumes snapshots api."""

from webob import exc
import webob

from cinder.api.openstack import common
from cinder.api.openstack import wsgi
from cinder.api.openstack import xmlutil
from cinder.api.openstack.volume import volumes
from cinder import exception
from cinder import flags
from cinder.openstack.common import log as logging
from cinder import utils
from cinder import volume


LOG = logging.getLogger(__name__)


FLAGS = flags.FLAGS


def _translate_snapshot_detail_view(context, snapshot):
    """Maps keys for snapshots details view."""

    d = _translate_snapshot_summary_view(context, snapshot)

    # NOTE(gagupta): No additional data / lookups at the moment
    return d


def _translate_snapshot_summary_view(context, snapshot):
    """Maps keys for snapshots summary view."""
    d = {}

    d['id'] = snapshot['id']
    d['created_at'] = snapshot['created_at']
    d['display_name'] = snapshot['display_name']
    d['display_description'] = snapshot['display_description']
    d['volume_id'] = snapshot['volume_id']
    d['status'] = snapshot['status']
    d['size'] = snapshot['volume_size']

    return d


def make_snapshot(elem):
    elem.set('id')
    elem.set('status')
    elem.set('size')
    elem.set('created_at')
    elem.set('display_name')
    elem.set('display_description')
    elem.set('volume_id')


class SnapshotTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('snapshot', selector='snapshot')
        make_snapshot(root)
        return xmlutil.MasterTemplate(root, 1)


class SnapshotsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('snapshots')
        elem = xmlutil.SubTemplateElement(root, 'snapshot',
                                          selector='snapshots')
        make_snapshot(elem)
        return xmlutil.MasterTemplate(root, 1)


class SnapshotsController(wsgi.Controller):
    """The Volumes API controller for the OpenStack API."""

    def __init__(self, ext_mgr=None):
        self.volume_api = volume.API()
        self.ext_mgr = ext_mgr
        super(SnapshotsController, self).__init__()

    @wsgi.serializers(xml=SnapshotTemplate)
    def show(self, req, id):
        """Return data about the given snapshot."""
        context = req.environ['cinder.context']

        try:
            vol = self.volume_api.get_snapshot(context, id)
        except exception.NotFound:
            raise exc.HTTPNotFound()

        return {'snapshot': _translate_snapshot_detail_view(context, vol)}

    def delete(self, req, id):
        """Delete a snapshot."""
        context = req.environ['cinder.context']

        LOG.audit(_("Delete snapshot with id: %s"), id, context=context)

        try:
            snapshot = self.volume_api.get_snapshot(context, id)
            self.volume_api.delete_snapshot(context, snapshot)
        except exception.NotFound:
            raise exc.HTTPNotFound()
        return webob.Response(status_int=202)

    @wsgi.serializers(xml=SnapshotsTemplate)
    def index(self, req):
        """Returns a summary list of snapshots."""
        return self._items(req, entity_maker=_translate_snapshot_summary_view)

    @wsgi.serializers(xml=SnapshotsTemplate)
    def detail(self, req):
        """Returns a detailed list of snapshots."""
        return self._items(req, entity_maker=_translate_snapshot_detail_view)

    def _items(self, req, entity_maker):
        """Returns a list of snapshots, transformed through entity_maker."""
        context = req.environ['cinder.context']

        search_opts = {}
        search_opts.update(req.GET)
        allowed_search_options = ('status', 'volume_id', 'display_name')
        volumes.remove_invalid_options(context, search_opts,
                                       allowed_search_options)

        snapshots = self.volume_api.get_all_snapshots(context,
                                                      search_opts=search_opts)
        limited_list = common.limited(snapshots, req)
        res = [entity_maker(context, snapshot) for snapshot in limited_list]
        return {'snapshots': res}

    @wsgi.serializers(xml=SnapshotTemplate)
    def create(self, req, body):
        """Creates a new snapshot."""
        context = req.environ['cinder.context']

        if not self.is_valid_body(body, 'snapshot'):
            raise exc.HTTPUnprocessableEntity()

        snapshot = body['snapshot']
        volume_id = snapshot['volume_id']
        volume = self.volume_api.get(context, volume_id)
        force = snapshot.get('force', False)
        msg = _("Create snapshot from volume %s")
        LOG.audit(msg, volume_id, context=context)

        if not utils.is_valid_boolstr(force):
            msg = _("Invalid value '%s' for force. ") % force
            raise exception.InvalidParameterValue(err=msg)

        if utils.bool_from_str(force):
            new_snapshot = self.volume_api.create_snapshot_force(context,
                                        volume,
                                        snapshot.get('display_name'),
                                        snapshot.get('display_description'))
        else:
            new_snapshot = self.volume_api.create_snapshot(context,
                                        volume,
                                        snapshot.get('display_name'),
                                        snapshot.get('display_description'))

        retval = _translate_snapshot_detail_view(context, new_snapshot)

        return {'snapshot': retval}


def create_resource(ext_mgr):
    return wsgi.Resource(SnapshotsController(ext_mgr))
