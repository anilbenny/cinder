# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 NetApp, Inc.
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
"""Unit tests for the NetApp-specific NFS driver module (netapp_nfs)"""

from cinder import context
from cinder import test
from cinder import exception

from cinder.volume import netapp_nfs
from cinder.volume import netapp
from cinder.volume import nfs
from mox import IsA
from mox import IgnoreArg
from mox import MockObject
from lxml import etree

import mox
import suds
import types


class FakeVolume(object):
    def __init__(self, size=0):
        self.size = size
        self.id = hash(self)
        self.name = None

    def __getitem__(self, key):
        return self.__dict__[key]


class FakeSnapshot(object):
    def __init__(self, volume_size=0):
        self.volume_name = None
        self.name = None
        self.volume_id = None
        self.volume_size = volume_size
        self.user_id = None
        self.status = None

    def __getitem__(self, key):
        return self.__dict__[key]


class FakeResponce(object):
    def __init__(self, status):
        """
        :param status: Either 'failed' or 'passed'
        """
        self.Status = status

        if status == 'failed':
            self.Reason = 'Sample error'


class NetappNfsDriverTestCase(test.TestCase):
    """Test case for NetApp specific NFS clone driver"""

    def setUp(self):
        self._driver = netapp_nfs.NetAppNFSDriver()
        self._mox = mox.Mox()

    def tearDown(self):
        self._mox.UnsetStubs()

    def test_check_for_setup_error(self):
        mox = self._mox
        drv = self._driver
        required_flags = [
            'netapp_wsdl_url',
            'netapp_login',
            'netapp_password',
            'netapp_server_hostname',
            'netapp_server_port']

        # check exception raises when flags are not set
        self.assertRaises(exception.CinderException,
                          drv.check_for_setup_error)

        # set required flags
        for flag in required_flags:
            setattr(netapp.FLAGS, flag, 'val')

        mox.StubOutWithMock(nfs.NfsDriver, 'check_for_setup_error')
        nfs.NfsDriver.check_for_setup_error()
        mox.ReplayAll()

        drv.check_for_setup_error()

        mox.VerifyAll()

        # restore initial FLAGS
        for flag in required_flags:
            delattr(netapp.FLAGS, flag)

    def test_do_setup(self):
        mox = self._mox
        drv = self._driver

        mox.StubOutWithMock(drv, 'check_for_setup_error')
        mox.StubOutWithMock(netapp_nfs.NetAppNFSDriver, '_get_client')

        drv.check_for_setup_error()
        netapp_nfs.NetAppNFSDriver._get_client()

        mox.ReplayAll()

        drv.do_setup(IsA(context.RequestContext))

        mox.VerifyAll()

    def test_create_snapshot(self):
        """Test snapshot can be created and deleted"""
        mox = self._mox
        drv = self._driver

        mox.StubOutWithMock(drv, '_clone_volume')
        drv._clone_volume(IgnoreArg(), IgnoreArg(), IgnoreArg())
        mox.ReplayAll()

        drv.create_snapshot(FakeSnapshot())

        mox.VerifyAll()

    def test_create_volume_from_snapshot(self):
        """Tests volume creation from snapshot"""
        drv = self._driver
        mox = self._mox
        volume = FakeVolume(1)
        snapshot = FakeSnapshot(2)

        self.assertRaises(exception.CinderException,
                          drv.create_volume_from_snapshot,
                          volume,
                          snapshot)

        snapshot = FakeSnapshot(1)

        location = '127.0.0.1:/nfs'
        expected_result = {'provider_location': location}
        mox.StubOutWithMock(drv, '_clone_volume')
        mox.StubOutWithMock(drv, '_get_volume_location')
        drv._clone_volume(IgnoreArg(), IgnoreArg(), IgnoreArg())
        drv._get_volume_location(IgnoreArg()).AndReturn(location)

        mox.ReplayAll()

        loc = drv.create_volume_from_snapshot(volume, snapshot)

        self.assertEquals(loc, expected_result)

        mox.VerifyAll()

    def _prepare_delete_snapshot_mock(self, snapshot_exists):
        drv = self._driver
        mox = self._mox

        mox.StubOutWithMock(drv, '_get_provider_location')
        mox.StubOutWithMock(drv, '_volume_not_present')

        if snapshot_exists:
            mox.StubOutWithMock(drv, '_execute')
            mox.StubOutWithMock(drv, '_get_volume_path')

        drv._get_provider_location(IgnoreArg())
        drv._volume_not_present(IgnoreArg(),
                                IgnoreArg()).AndReturn(not snapshot_exists)

        if snapshot_exists:
            drv._get_volume_path(IgnoreArg(), IgnoreArg())
            drv._execute('rm', None, run_as_root=True)

        mox.ReplayAll()

        return mox

    def test_delete_existing_snapshot(self):
        drv = self._driver
        mox = self._prepare_delete_snapshot_mock(True)

        drv.delete_snapshot(FakeSnapshot())

        mox.VerifyAll()

    def test_delete_missing_snapshot(self):
        drv = self._driver
        mox = self._prepare_delete_snapshot_mock(False)

        drv.delete_snapshot(FakeSnapshot())

        mox.VerifyAll()

    def _prepare_clone_mock(self, status):
        drv = self._driver
        mox = self._mox

        volume = FakeVolume()
        setattr(volume, 'provider_location', '127.0.0.1:/nfs')

        drv._client = MockObject(suds.client.Client)
        drv._client.factory = MockObject(suds.client.Factory)
        drv._client.service = MockObject(suds.client.ServiceSelector)

        # ApiProxy() method is generated by ServiceSelector at runtime from the
        # XML, so mocking is impossible.
        setattr(drv._client.service,
                'ApiProxy',
                types.MethodType(lambda *args, **kwargs: FakeResponce(status),
                                 suds.client.ServiceSelector))
        mox.StubOutWithMock(drv, '_get_host_id')
        mox.StubOutWithMock(drv, '_get_full_export_path')

        drv._get_host_id(IgnoreArg()).AndReturn('10')
        drv._get_full_export_path(IgnoreArg(), IgnoreArg()).AndReturn('/nfs')

        return mox

    def test_successfull_clone_volume(self):
        drv = self._driver
        mox = self._prepare_clone_mock('passed')

        mox.ReplayAll()

        volume_name = 'volume_name'
        clone_name = 'clone_name'
        volume_id = volume_name + str(hash(volume_name))

        drv._clone_volume(volume_name, clone_name, volume_id)

        mox.VerifyAll()

    def test_failed_clone_volume(self):
        drv = self._driver
        mox = self._prepare_clone_mock('failed')

        mox.ReplayAll()

        volume_name = 'volume_name'
        clone_name = 'clone_name'
        volume_id = volume_name + str(hash(volume_name))

        self.assertRaises(exception.CinderException,
                          drv._clone_volume,
                          volume_name, clone_name, volume_id)

        mox.VerifyAll()


class NetappCmodeNfsDriverTestCase(test.TestCase):
    """Test case for NetApp C Mode specific NFS clone driver"""

    def setUp(self):
        self._mox = mox.Mox()
        self._custom_setup()

    def _custom_setup(self):
        self._driver = netapp_nfs.NetAppCmodeNfsDriver()

    def tearDown(self):
        self._mox.UnsetStubs()

    def test_check_for_setup_error(self):
        mox = self._mox
        drv = self._driver
        required_flags = [
            'netapp_wsdl_url',
            'netapp_login',
            'netapp_password',
            'netapp_server_hostname',
            'netapp_server_port']

        # check exception raises when flags are not set
        self.assertRaises(exception.CinderException,
                          drv.check_for_setup_error)

        # set required flags
        for flag in required_flags:
            setattr(netapp.FLAGS, flag, 'val')

        mox.ReplayAll()

        drv.check_for_setup_error()

        mox.VerifyAll()

        # restore initial FLAGS
        for flag in required_flags:
            delattr(netapp.FLAGS, flag)

    def test_do_setup(self):
        mox = self._mox
        drv = self._driver

        mox.StubOutWithMock(drv, 'check_for_setup_error')
        mox.StubOutWithMock(netapp_nfs.NetAppCmodeNfsDriver, '_get_client')

        drv.check_for_setup_error()
        netapp_nfs.NetAppCmodeNfsDriver._get_client()

        mox.ReplayAll()

        drv.do_setup(IsA(context.RequestContext))

        mox.VerifyAll()

    def test_create_snapshot(self):
        """Test snapshot can be created and deleted"""
        mox = self._mox
        drv = self._driver

        mox.StubOutWithMock(drv, '_clone_volume')
        drv._clone_volume(IgnoreArg(), IgnoreArg(), IgnoreArg())
        mox.ReplayAll()

        drv.create_snapshot(FakeSnapshot())

        mox.VerifyAll()

    def test_create_volume_from_snapshot(self):
        """Tests volume creation from snapshot"""
        drv = self._driver
        mox = self._mox
        volume = FakeVolume(1)
        snapshot = FakeSnapshot(2)

        self.assertRaises(exception.CinderException,
                          drv.create_volume_from_snapshot,
                          volume,
                          snapshot)

        snapshot = FakeSnapshot(1)

        location = '127.0.0.1:/nfs'
        expected_result = {'provider_location': location}
        mox.StubOutWithMock(drv, '_clone_volume')
        mox.StubOutWithMock(drv, '_get_volume_location')
        drv._clone_volume(IgnoreArg(), IgnoreArg(), IgnoreArg())
        drv._get_volume_location(IgnoreArg()).AndReturn(location)

        mox.ReplayAll()

        loc = drv.create_volume_from_snapshot(volume, snapshot)

        self.assertEquals(loc, expected_result)

        mox.VerifyAll()

    def _prepare_delete_snapshot_mock(self, snapshot_exists):
        drv = self._driver
        mox = self._mox

        mox.StubOutWithMock(drv, '_get_provider_location')
        mox.StubOutWithMock(drv, '_volume_not_present')

        if snapshot_exists:
            mox.StubOutWithMock(drv, '_execute')
            mox.StubOutWithMock(drv, '_get_volume_path')

        drv._get_provider_location(IgnoreArg())
        drv._volume_not_present(IgnoreArg(), IgnoreArg())\
            .AndReturn(not snapshot_exists)

        if snapshot_exists:
            drv._get_volume_path(IgnoreArg(), IgnoreArg())
            drv._execute('rm', None, run_as_root=True)

        mox.ReplayAll()

        return mox

    def test_delete_existing_snapshot(self):
        drv = self._driver
        mox = self._prepare_delete_snapshot_mock(True)

        drv.delete_snapshot(FakeSnapshot())

        mox.VerifyAll()

    def test_delete_missing_snapshot(self):
        drv = self._driver
        mox = self._prepare_delete_snapshot_mock(False)

        drv.delete_snapshot(FakeSnapshot())

        mox.VerifyAll()

    def _prepare_clone_mock(self, status):
        drv = self._driver
        mox = self._mox

        volume = FakeVolume()
        setattr(volume, 'provider_location', '127.0.0.1:/nfs')

        drv._client = MockObject(suds.client.Client)
        drv._client.factory = MockObject(suds.client.Factory)
        drv._client.service = MockObject(suds.client.ServiceSelector)
        # CloneNasFile method is generated by ServiceSelector at runtime from
        # the
        # XML, so mocking is impossible.
        setattr(drv._client.service,
                'CloneNasFile',
                types.MethodType(lambda *args, **kwargs: FakeResponce(status),
                                 suds.client.ServiceSelector))
        mox.StubOutWithMock(drv, '_get_host_ip')
        mox.StubOutWithMock(drv, '_get_export_path')

        drv._get_host_ip(IgnoreArg()).AndReturn('127.0.0.1')
        drv._get_export_path(IgnoreArg()).AndReturn('/nfs')
        return mox

    def test_clone_volume(self):
        drv = self._driver
        mox = self._prepare_clone_mock('passed')

        mox.ReplayAll()

        volume_name = 'volume_name'
        clone_name = 'clone_name'
        volume_id = volume_name + str(hash(volume_name))

        drv._clone_volume(volume_name, clone_name, volume_id)

        mox.VerifyAll()


class NetappDirectCmodeNfsDriverTestCase(NetappCmodeNfsDriverTestCase):
    """Test direct NetApp C Mode driver"""
    def _custom_setup(self):
        self._driver = netapp_nfs.NetAppDirectCmodeNfsDriver()

    def test_check_for_setup_error(self):
        mox = self._mox
        drv = self._driver
        required_flags = [
            'netapp_transport_type',
            'netapp_login',
            'netapp_password',
            'netapp_server_hostname',
            'netapp_server_port']

        # check exception raises when flags are not set
        self.assertRaises(exception.CinderException,
                          drv.check_for_setup_error)

        # set required flags
        for flag in required_flags:
            setattr(netapp.FLAGS, flag, 'val')

        mox.ReplayAll()

        drv.check_for_setup_error()

        mox.VerifyAll()

        # restore initial FLAGS
        for flag in required_flags:
            delattr(netapp.FLAGS, flag)

    def test_do_setup(self):
        mox = self._mox
        drv = self._driver

        mox.StubOutWithMock(drv, 'check_for_setup_error')
        mox.StubOutWithMock(netapp_nfs.NetAppDirectCmodeNfsDriver,
                            '_get_client')
        mox.StubOutWithMock(drv, '_do_custom_setup')

        drv.check_for_setup_error()
        netapp_nfs.NetAppDirectNfsDriver._get_client()
        drv._do_custom_setup(IgnoreArg())

        mox.ReplayAll()

        drv.do_setup(IsA(context.RequestContext))

        mox.VerifyAll()

    def _prepare_clone_mock(self, status):
        drv = self._driver
        mox = self._mox

        volume = FakeVolume()
        setattr(volume, 'provider_location', '127.0.0.1:/nfs')

        mox.StubOutWithMock(drv, '_get_host_ip')
        mox.StubOutWithMock(drv, '_get_export_path')
        mox.StubOutWithMock(drv, '_get_if_info_by_ip')
        mox.StubOutWithMock(drv, '_get_vol_by_junc_vserver')
        mox.StubOutWithMock(drv, '_clone_file')

        drv._get_host_ip(IgnoreArg()).AndReturn('127.0.0.1')
        drv._get_export_path(IgnoreArg()).AndReturn('/nfs')
        drv._get_if_info_by_ip('127.0.0.1').AndReturn(
            self._prepare_info_by_ip_response())
        drv._get_vol_by_junc_vserver('openstack', '/nfs').AndReturn('nfsvol')
        drv._clone_file('nfsvol', 'volume_name', 'clone_name',
                        'openstack')
        return mox

    def _prepare_info_by_ip_response(self):
        res = """<attributes-list>
        <net-interface-info>
        <address>127.0.0.1</address>
        <administrative-status>up</administrative-status>
        <current-node>fas3170rre-cmode-01</current-node>
        <current-port>e1b-1165</current-port>
        <data-protocols>
          <data-protocol>nfs</data-protocol>
        </data-protocols>
        <dns-domain-name>none</dns-domain-name>
        <failover-group/>
        <failover-policy>disabled</failover-policy>
        <firewall-policy>data</firewall-policy>
        <home-node>fas3170rre-cmode-01</home-node>
        <home-port>e1b-1165</home-port>
        <interface-name>nfs_data1</interface-name>
        <is-auto-revert>false</is-auto-revert>
        <is-home>true</is-home>
        <netmask>255.255.255.0</netmask>
        <netmask-length>24</netmask-length>
        <operational-status>up</operational-status>
        <role>data</role>
        <routing-group-name>c10.63.165.0/24</routing-group-name>
        <use-failover-group>disabled</use-failover-group>
        <vserver>openstack</vserver>
      </net-interface-info></attributes-list>"""
        response_el = etree.XML(res)
        return netapp.NaElement(response_el).get_children()

    def test_clone_volume(self):
        drv = self._driver
        mox = self._prepare_clone_mock('pass')

        mox.ReplayAll()

        volume_name = 'volume_name'
        clone_name = 'clone_name'
        volume_id = volume_name + str(hash(volume_name))

        drv._clone_volume(volume_name, clone_name, volume_id)

        mox.VerifyAll()


class NetappDirect7modeNfsDriverTestCase(NetappDirectCmodeNfsDriverTestCase):
    """Test direct NetApp C Mode driver"""
    def _custom_setup(self):
        self._driver = netapp_nfs.NetAppDirect7modeNfsDriver()

    def test_check_for_setup_error(self):
        mox = self._mox
        drv = self._driver
        required_flags = [
            'netapp_transport_type',
            'netapp_login',
            'netapp_password',
            'netapp_server_hostname',
            'netapp_server_port']

        # check exception raises when flags are not set
        self.assertRaises(exception.CinderException,
                          drv.check_for_setup_error)

        # set required flags
        for flag in required_flags:
            setattr(netapp.FLAGS, flag, 'val')

        mox.ReplayAll()

        drv.check_for_setup_error()

        mox.VerifyAll()

        # restore initial FLAGS
        for flag in required_flags:
            delattr(netapp.FLAGS, flag)

    def test_do_setup(self):
        mox = self._mox
        drv = self._driver

        mox.StubOutWithMock(drv, 'check_for_setup_error')
        mox.StubOutWithMock(netapp_nfs.NetAppDirect7modeNfsDriver,
                            '_get_client')
        mox.StubOutWithMock(drv, '_do_custom_setup')

        drv.check_for_setup_error()
        netapp_nfs.NetAppDirectNfsDriver._get_client()
        drv._do_custom_setup(IgnoreArg())

        mox.ReplayAll()

        drv.do_setup(IsA(context.RequestContext))

        mox.VerifyAll()

    def _prepare_clone_mock(self, status):
        drv = self._driver
        mox = self._mox

        volume = FakeVolume()
        setattr(volume, 'provider_location', '127.0.0.1:/nfs')

        mox.StubOutWithMock(drv, '_get_export_path')
        mox.StubOutWithMock(drv, '_get_actual_path_for_export')
        mox.StubOutWithMock(drv, '_start_clone')
        mox.StubOutWithMock(drv, '_wait_for_clone_finish')
        if status == 'fail':
            mox.StubOutWithMock(drv, '_clear_clone')

        drv._get_export_path(IgnoreArg()).AndReturn('/nfs')
        drv._get_actual_path_for_export(IgnoreArg()).AndReturn('/vol/vol1/nfs')
        drv._start_clone(IgnoreArg(), IgnoreArg()).AndReturn(('1', '2'))
        if status == 'fail':
            drv._wait_for_clone_finish('1', '2').AndRaise(
                netapp.NaApiError('error', 'error'))
            drv._clear_clone('1')
        else:
            drv._wait_for_clone_finish('1', '2')
        return mox

    def test_clone_volume_clear(self):
        drv = self._driver
        mox = self._prepare_clone_mock('fail')

        mox.ReplayAll()

        volume_name = 'volume_name'
        clone_name = 'clone_name'
        volume_id = volume_name + str(hash(volume_name))
        try:
            drv._clone_volume(volume_name, clone_name, volume_id)
        except Exception as e:
            if isinstance(e, netapp.NaApiError):
                pass
            else:
                raise e

        mox.VerifyAll()
