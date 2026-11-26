"""Testes OFFLINE de STUN, RUDP, PSN, H.264 e controles; sem alegar sessão Sony real."""
import asyncio
import base64
import json
import socket
import struct
from types import SimpleNamespace

import httpx
import pytest

from remoteplay.remote.stun import (COOKIE, RESPONSE, XOR_MAPPED_ADDRESS, StunClient,
                                    make_binding_request, parse_binding_response)
from remoteplay.remote.rudp import (MAGIC, Packet, PacketType, SceRudp, pack, unpack)
from remoteplay.remote.holepunch import Candidate, CandidatePunch, PunchFailed
from remoteplay.remote.control_probe import RESPONSE as PSN_RESPONSE, _identity, _packet, select_control_candidate
from remoteplay.psn.devices import DeviceDiscoveryUnavailable, list_psn_devices, parse_ps5_clients
from remoteplay.psn.session_manager import SessionManagerError, create_session, parse_created, delete_session
from remoteplay.media.webrtc_control import ControlChannel, ControlProtocolError, parse_command
from remoteplay.media.encoded_h264 import EncodedH264Buffer
from pyremoteplay.av import AVStream


@pytest.mark.asyncio
async def test_control_probe_requires_matching_nonce_and_endpoint():
    candidate = {'addr': '192.0.2.20', 'port': 9296, 'type': 'LOCAL'}
    endpoint = (candidate['addr'], candidate['port'])
    own = {'localHashedId': base64.b64encode(b'a' * 20), 'sid': 12}
    peer = {'localHashedId': base64.b64encode(b'b' * 20), 'sid': 34, 'candidate': [candidate]}

    class ProbeSocket:
        def __init__(self):
            self.transport = self
            self.incoming = asyncio.Queue()
            self.received = 0

        def sendto(self, request, remote):
            assert remote == endpoint
            identity = _identity(peer, own)
            nonce = request[75:80]
            self.incoming.put_nowait((_packet(PSN_RESPONSE, identity, nonce), (remote[0], remote[1] + 1)))
            wrong_nonce = bytes([nonce[0] ^ 1]) + nonce[1:]
            self.incoming.put_nowait((_packet(PSN_RESPONSE, identity, wrong_nonce), remote))
            self.incoming.put_nowait((_packet(PSN_RESPONSE, identity, nonce), remote))

        async def receive_peer_packet(self):
            self.received += 1
            return await self.incoming.get()

    udp = ProbeSocket()
    assert await select_control_candidate(udp, own, peer) == candidate
    assert udp.received == 3


@pytest.mark.asyncio
async def test_rudp_cookie_can_reuse_the_negotiated_udp_transport():
    endpoint = ('192.0.2.20', 9296)
    channel = SceRudp(endpoint)
    sent = []

    class Transport:
        def sendto(self, data, address):
            assert address == endpoint
            request = unpack(data)
            sent.append(request.type)
            if request.type == PacketType.INIT_REQUEST:
                response = Packet(PacketType.INIT_RESPONSE | 0x30, bytes(8) + b'synthetic-cookie')
            else:
                assert request.payload[14:] == b'synthetic-cookie'
                response = Packet(PacketType.COOKIE_RESPONSE & 0xff00, b'\x00\x2a')
            channel.receive_datagram(pack(response), endpoint)

    channel.attach(Transport())
    try:
        assert await channel.negotiate_cookie() == 43
        assert sent == [PacketType.INIT_REQUEST, PacketType.COOKIE_REQUEST]
    finally:
        await channel.close()


@pytest.mark.asyncio
async def test_rudp_session_request_reads_nested_http_response():
    endpoint = ('192.0.2.20', 9296)
    channel = SceRudp(endpoint)
    request = b'GET /sie/ps4/rp/sess/init HTTP/1.1\r\n\r\n'

    class Transport:
        def sendto(self, data, address):
            assert address == endpoint
            packet = unpack(data)
            assert packet.type == PacketType.SESSION_MESSAGE
            assert packet.subpacket.payload[2:] == request
            reply = Packet(0x0630, b'\x00\x2aHTTP/1.1 200 OK\r\nRP-Nonce: synthetic\r\n\r\nbody')
            channel.receive_datagram(pack(Packet(PacketType.SESSION_MESSAGE, b'', reply)), endpoint)

    channel.attach(Transport())
    try:
        response = await channel.request_session(30, request)
        assert (response.status, response.headers, response.body, response.remote_counter) == (
            200, {'rp-nonce': 'synthetic'}, b'body', 43,
        )
    finally:
        await channel.close()


def test_av_stream_reassembles_reordered_units_and_skips_duplicates():
    completed = []
    stream = AVStream(AVStream.TYPE_AUDIO, b'', completed.append, lambda *_: None)

    def unit(frame, index, data):
        return SimpleNamespace(frame_index=frame, unit_index=index, data=data,
                               frame_length=2, frame_length_src=2, frame_size_audio=1,
                               is_last_src=index == 1, is_fec=False,
                               index=frame * 2 + index)

    stream.handle(unit(1, 1, b'b'))
    stream.handle(unit(2, 0, b'c'))
    stream.handle(unit(1, 0, b'a'))
    stream.handle(unit(1, 1, b'b'))
    stream.handle(unit(2, 1, b'd'))
    assert completed == [b'ab', b'cd']


def _stun_reply(txid, address='192.0.2.44', port=53014):
    raw = socket.inet_aton(address)
    key = struct.pack('!I', COOKIE)
    body = b'\x00\x01' + struct.pack('!H', port ^ (COOKIE >> 16)) + bytes(a ^ b for a, b in zip(raw, key))
    return struct.pack('!HHI12sHH', RESPONSE, 12, COOKIE, txid, XOR_MAPPED_ADDRESS, 8) + body


def test_stun_validates_transaction_and_decodes_mapping():
    packet, txid = make_binding_request(b'a' * 12)
    assert packet == struct.pack('!HHI12s', 1, 0, COOKIE, b'a' * 12)
    reply = _stun_reply(txid)
    assert parse_binding_response(reply, txid) == ('192.0.2.44', 53014)
    with pytest.raises(ValueError):
        parse_binding_response(reply, b'b' * 12)
    with pytest.raises(ValueError):
        parse_binding_response(reply[:20], txid)


@pytest.mark.asyncio
async def test_stun_socket_receives_genuine_udp_response_on_loopback():
    class MockStun(asyncio.DatagramProtocol):
        def connection_made(self, t): self.transport = t
        def datagram_received(self, data, addr):
            self.transport.sendto(_stun_reply(data[8:20], '198.51.100.10', 41000), addr)

    loop = asyncio.get_running_loop()
    server, _ = await loop.create_datagram_endpoint(MockStun, local_addr=('127.0.0.1', 0))
    try:
        port = server.get_extra_info('sockname')[1]
        async with StunClient() as client:
            mapping = await client.probe('127.0.0.1', port, timeout=1.0)
            assert (mapping.address, mapping.port) == ('198.51.100.10', 41000)
            assert mapping.local_port > 0
    finally:
        server.close()


def test_rudp_wire_format_and_invalid_packets():
    child = Packet(PacketType.CTRL_MESSAGE, b'\x00\x02OK')
    parent = Packet(PacketType.SESSION_MESSAGE, b'\x00\x01\x00\x02', child)
    raw = pack(parent)
    assert raw[2:6] == struct.pack('!I', MAGIC)
    assert unpack(raw) == parent
    assert unpack(raw).subpacket.remote_counter == 3
    with pytest.raises(ValueError): unpack(raw[:5])
    with pytest.raises(ValueError): unpack(raw[:2] + b'BAD!' + raw[6:])
    with pytest.raises(ValueError): pack(Packet(PacketType.CTRL_MESSAGE, b'x' * 5000))


@pytest.mark.asyncio
async def test_rudp_real_loopback_ack_releases_pending():
    received = []

    class AckPeer(asyncio.DatagramProtocol):
        def connection_made(self, t): self.transport = t
        def datagram_received(self, raw, addr):
            pkt = unpack(raw)
            if pkt.type == PacketType.CTRL_MESSAGE:
                received.append(raw)
                if len(received) % 2:
                    return
                ack = (int.from_bytes(pkt.payload[:2], 'big') + 1) & 65535
                self.transport.sendto(pack(Packet(PacketType.ACK, struct.pack('!HH2s', 1, ack, b'\x00\x92'))), addr)
    loop = asyncio.get_running_loop()
    server, _ = await loop.create_datagram_endpoint(AckPeer, local_addr=('127.0.0.1', 0))
    rudp = SceRudp(('127.0.0.1', server.get_extra_info('sockname')[1]), retry_interval=.03, max_retries=3)
    try:
        await rudp.open()
        first = await asyncio.wait_for(rudp.send_ctrl(b'teste', wait_ack=True), timeout=1)
        second = await asyncio.wait_for(rudp.send_ctrl(b'outro', wait_ack=True), timeout=1)
        assert second == (first + 1) & 65535
        assert len(received) == 4
        assert received[0] == received[1]
        assert received[2] == received[3]
        assert rudp.stats()['pending_acks'] == 0
        assert rudp.stats()['packets_received'] >= 1
    finally:
        await rudp.close()
        server.close()
    assert rudp.closed


@pytest.mark.asyncio
async def test_holepunch_requires_verified_answer_not_only_udp_send():
    class Peer(asyncio.DatagramProtocol):
        def connection_made(self, t): self.transport = t
        def datagram_received(self, data, addr): self.transport.sendto(b'AUTH:' + data, addr)
    loop = asyncio.get_running_loop()
    server, _ = await loop.create_datagram_endpoint(Peer, local_addr=('127.0.0.1', 0))
    punch = await CandidatePunch().open()
    c = Candidate('127.0.0.1', server.get_extra_info('sockname')[1])
    try:
        with pytest.raises(PunchFailed):
            await punch.punch([c], b'probe', lambda body, addr: False, timeout=.09, interval=.03)
        result = await punch.punch([c], b'probe', lambda body, addr: body == b'AUTH:probe', timeout=1)
        assert result == c and punch.peer == (c.address, c.port)
    finally:
        await punch.close()
        server.close()


def test_ps5_devices_parse_real_schema_not_ps4():
    data = {'clients': [{'duid': 'ABCD1122', 'device': {'name': 'PS5 Sala', 'enabledFeatures': ['remotePlay']}}]}
    dev = parse_ps5_clients(data)[0]
    assert dev.platform == 'PS5' and dev.remoteplay_enabled and dev.duid == 'abcd1122'
    with pytest.raises(DeviceDiscoveryUnavailable): parse_ps5_clients({'clients': [{}]})
    with pytest.raises(DeviceDiscoveryUnavailable): parse_ps5_clients({'clients': 'fake'})


@pytest.mark.asyncio
async def test_ps5_discovery_calls_sony_endpoint_via_mock_only():
    calls = []
    def handler(request):
        calls.append(str(request.url))
        assert request.headers['Authorization'] == 'Bearer secure-token'
        assert request.url.params['platform'] == 'PS5'
        return httpx.Response(200, json={'clients': [{'duid': 'ccdd', 'device': {'name': 'PS5 Teste', 'enabledFeatures': []}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await list_psn_devices(client, 'secure-token')
        assert response[0]['name'] == 'PS5 Teste' and not response[0]['remoteplay_enabled']
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_psn_session_creation_and_cleanup_http_mock():
    import uuid
    sid = str(uuid.uuid4())
    calls = []
    def handler(request):
        calls.append((request.method, str(request.url)))
        assert request.headers['Authorization'] == 'Bearer TEST'
        if request.method == 'POST':
            data = json.loads(request.content)
            assert data['remotePlaySessions'][0]['members'][0]['pushContexts'][0]['pushContextId'] == 'push-1'
            return httpx.Response(200, json={'remotePlaySessions': [{'sessionId': sid, 'members': [{'accountId': '12345'}]}]})
        if request.method == 'DELETE':
            assert request.headers['X-PSN-SESSION-MANAGER-SESSION-IDS'] == sid
            return httpx.Response(204)
        return httpx.Response(405)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        res = await create_session(client, 'TEST', 'push-1')
        assert res.session_id == sid and res.account_id == '12345'
        await delete_session(client, 'TEST', sid)
    assert [name for name, url in calls] == ['POST', 'DELETE']
    with pytest.raises(SessionManagerError):
        parse_created({'remotePlaySessions': [{'sessionId': 'fake'}]})


def test_web_rtc_controls_are_validated():
    assert parse_command('{"type":"button","name":"cross","pressed":true}')['name'] == 'cross'
    assert parse_command('{"type":"axis","name":"left_x","value":0.8}')['value'] == 0.8
    for msg in ('{"type":"axis","name":"left_x","value":Infinity}',
                '{"type":"button","name":"ps"}', '{"type":"axis","name":"right_x","value":3}',
                '{"type":"button","name":"cross","role":"admin"}', 'x' * 600):
        with pytest.raises(ControlProtocolError): parse_command(msg)


@pytest.mark.asyncio
async def test_web_rtc_control_queue_calls_real_callback_once_per_valid_packet():
    commands = []
    channel = ControlChannel(lambda x: commands.append(x), max_rate=10).start()
    try:
        assert channel.submit('{"type":"button","name":"circle","pressed":true}')
        assert not channel.submit('{"type":"button","name":"ps","pressed":true}')
        await asyncio.wait_for(channel.queue.join(), timeout=1)
        assert commands == [{'type': 'button', 'name': 'circle', 'pressed': True}]
    finally:
        await channel.stop()


def test_encoded_h264_buffer_waits_for_idr_and_drops_older_frames():
    q = EncodedH264Buffer(max_frames=2)
    sps_pps = b'\x00\x00\x00\x01\x67\x42\x00\x00\x01\x68\xce'
    p = b'\x00\x00\x01\x41\x11'
    idr = b'\x00\x00\x01\x65\x88'
    assert q.nal_types(sps_pps+idr) == (7, 8, 5)
    assert not q.push(p)
    assert q.push(sps_pps+idr)
    assert q.push(p) and q.push(p)
    assert q.next_frame(0)[0] == 3
    assert q.dropped == 1


@pytest.mark.asyncio
async def test_unordered_control_packet_sequence_drops_stale_and_duplicate_buttons():
    got = []
    channel = ControlChannel(lambda command: got.append(command)).start()
    try:
        press = '{"type":"button","name":"cross","pressed":true,"seq":8}'
        release = '{"type":"button","name":"cross","pressed":false,"seq":9}'
        assert channel.submit(press)
        assert not channel.submit(press)
        assert channel.submit(release)
        assert not channel.submit(press)  # chegou atrasado na rede
        await asyncio.wait_for(channel.queue.join(), 1)
        assert got == [
            {'type': 'button', 'name': 'cross', 'pressed': True},
            {'type': 'button', 'name': 'cross', 'pressed': False},
        ]
        with pytest.raises(ControlProtocolError):
            parse_command('{"type":"axis","name":"left_x","value":0,"seq":false}')
    finally:
        await channel.stop()
