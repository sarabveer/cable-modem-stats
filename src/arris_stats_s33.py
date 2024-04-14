"""
  Pull stats from Arris S33
"""

import time
import hmac
import logging
import requests

def get_credential(config):
  """ Get the cookie credential by sending the
    username and password pair for basic auth. They
    also want the pair as a base64 encoded get req param
  """
  logging.info('Obtaining login session from modem')

  ip = config['modem_ip']
  username = config['modem_username']
  password = config['modem_password']
  verify_ssl = config['modem_verify_ssl']
  url = "https://{}/HNAP1/".format(ip)

  payload = {
    "Login": {
      "Action": "request",
      "Username": username,
      "LoginPassword": "",
      "Captcha": "",
      "PrivateLogin": password,
    }
  }

  soap_action = '"http://purenetworks.com/HNAP1/Login"'

  headers = {
    "Accept": "application/json",
    "SOAPACTION": soap_action,
    "HNAP_AUTH": hnap_auth_header(private_key=None, soap_action=soap_action),
  }
  soap_action = '"http://purenetworks.com/HNAP1/Login"'

  # This is going to respond with our "credential", which is a hash that we
  # have to send as a cookie with subsequent requests
  try:
    resp = requests.post(
      url=url,
      json=payload,
      headers=headers,
      verify=verify_ssl,
      timeout=config['request_timeout']
    )

    if resp.status_code != 200:
      logging.error('Error requesting login with %s', url)
      logging.error('Status code: %s', resp.status_code)
      logging.error('Reason: %s', resp.reason)
      resp.close()
      return None

    response_obj = resp.json()
    public_key = response_obj["LoginResponse"]["PublicKey"]
    uid = response_obj["LoginResponse"]["Cookie"]
    challenge_msg = response_obj["LoginResponse"]["Challenge"]
    resp.close()

    private_key = arris_hmac(
      key=(public_key + password).encode("utf-8"),
      msg=challenge_msg.encode("utf-8"),
    )

    payload["Login"]["Action"] = "login"
    payload["Login"]["LoginPassword"] = arris_hmac(
      key=private_key.encode("utf-8"),
      msg=challenge_msg.encode("utf-8"),
    )

    headers["HNAP_AUTH"] = hnap_auth_header(private_key=private_key, soap_action=soap_action)
    headers["Cookie"] = (
      "Secure; Secure; "  # double secure is strange, but it's how they do it
      f"uid={uid}; "
      f"PrivateKey={private_key}"
    )

    resp = requests.post(
      url=url,
      json=payload,
      headers=headers,
      verify=verify_ssl,
      timeout=config['request_timeout']
    )

    if resp.status_code != 200:
      logging.error('Error authenticating with %s', url)
      logging.error('Status code: %s', resp.status_code)
      logging.error('Reason: %s', resp.reason)
      resp.close()
      return None
    
    login_result = resp.json()["LoginResponse"]["LoginResult"]
    if login_result != "OK":
      logging.error('Error authenticating with %s', url)
      logging.error(f"Reason: Got {login_result} login result (expecting OK)")
      resp.close()
      return None

    resp.close()
  except Exception as exception:
    logging.error(exception)
    logging.error('Error authenticating with %s', url)
    return None

  return { 'uid': uid, 'private_key': private_key }


def get_json(config, credential):
  """ Get the status page from the modem
    return the raw html
  """

  ip = config['modem_ip']
  verify_ssl = config['modem_verify_ssl']
  url = "https://{}/HNAP1/".format(ip)

  soap_action = '"http://purenetworks.com/HNAP1/GetMultipleHNAPs"'
  headers = {
    "Accept": "application/json",
    "SOAPACTION": soap_action,
    "HNAP_AUTH": hnap_auth_header(private_key=credential["private_key"], soap_action=soap_action),
    "Cookie": (
      "Secure; Secure; "  # double secure is strange, but how they do it
      f"uid={credential['uid']}; "
      f"PrivateKey={credential['private_key']}"
    )
  }
  payload = {
    "GetMultipleHNAPs": {
      "GetCustomerStatusDownstreamChannelInfo": "",
      "GetCustomerStatusUpstreamChannelInfo": "",
    }
  }

  logging.info('Retreiving stats from %s', url)

  try:
    resp = requests.post(
      url=url,
      json=payload,
      headers=headers,
      verify=verify_ssl,
      timeout=config['request_timeout']
    )
    if resp.status_code != 200:
      logging.error('Error retreiving json from %s', url)
      logging.error('Status code: %s', resp.status_code)
      logging.error('Reason: %s', resp.reason)
      return None
    status_json = resp.json()["GetMultipleHNAPsResponse"]
    resp.close()
  except Exception as exception:
    logging.error(exception)
    logging.error('Error retreiving html from %s', url)
    return None

  return status_json


def parse_json(json):
  """ Parse the JSON into the modem stats dict """
  logging.info('Parsing JSON for modem model s33')

  stats = {}

  # downstream table
  stats['downstream'] = []
  for channel in json["GetCustomerStatusDownstreamChannelInfoResponse"]["CustomerConnDownstreamChannel"].split("|+|"):
    (
      channel_num,
      lock_status,
      modulation,
      channel_id,
      frequency,
      power,
      snr,
      corrected,
      uncorrectables,
      _,
    ) = channel.split("^")

    stats['downstream'].append({
      'channel_id': channel_id,
      'modulation': modulation,
      'frequency': frequency,
      'power': power,
      'snr': snr,
      'corrected': corrected,
      'uncorrectables': uncorrectables
    })

  logging.debug('downstream stats: %s', stats['downstream'])
  if not stats['downstream']:
    logging.error('Failed to get any downstream stats! Probably a parsing issue in parse_json()')

  # upstream table
  stats['upstream'] = []
  for channel in json["GetCustomerStatusUpstreamChannelInfoResponse"]["CustomerConnUpstreamChannel"].split("|+|"):
    (
      channel_num,
      lock_status,
      channel_type,
      channel_id,
      width,
      frequency,
      power,
      _,
    ) = channel.split("^")
    stats['upstream'].append({
      'channel_id': channel_id,
      'channel_type': channel_type,
      'frequency': frequency,
      'width': width,
      'power': power,
    })

  logging.debug('upstream stats: %s', stats['upstream'])
  if not stats['upstream']:
    logging.error('Failed to get any upstream stats! Probably a parsing issue in parse_json()')

  return stats

# Taken from https://github.com/t-mart/ispee/blob/master/src/ispee/s33.py
def arris_hmac(key: bytes, msg: bytes) -> str:
  """HMAC a message with a key in the way the arris s33 does it."""
  return (
  hmac.new(
    key=key,
    msg=msg,
    digestmod="md5",
  )
  .hexdigest()
  .upper()
  )

def hnap_auth_header(private_key: str, soap_action: str) -> str:
  """Return a value to be used for the custom HNAP_AUTH http header."""
  # this method is not contingent on already being logged in. there's a fallback
  # for when we're not logged in.
  if private_key is None:
    private_key = "withoutloginkey"

  # wierd... shrug. just following the javascript impl.
  cur_time_millis = str((time.time_ns() // 10**6) % 2_000_000_000_000)

  auth_part = arris_hmac(
    private_key.encode("utf-8"),
    (cur_time_millis + soap_action).encode("utf-8"),
  )

  return f"{auth_part} {cur_time_millis}"
