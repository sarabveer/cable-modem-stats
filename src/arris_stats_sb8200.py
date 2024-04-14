"""
  Pull stats from Arris SB8200
"""
# pylint: disable=line-too-long

import base64
import logging
import requests
from bs4 import BeautifulSoup

def get_credential(config):
  """ Get the cookie credential by sending the
    username and password pair for basic auth. They
    also want the pair as a base64 encoded get req param
  """
  logging.info('Obtaining login session from modem')

  if config["modem_ssl"]:
    url = f"https://{config['modem_ip']}/cmconnectionstatus.html"
  else:
    url = f"http://{config['modem_ip']}/cmconnectionstatus.html"

  username = config['modem_username']
  password = config['modem_password']
  verify_ssl = config['modem_verify_ssl']

  # We have to send a request with the username and password
  # encoded as a url param.  Look at the Javascript from the
  # login page for more info on the following.
  token = username + ":" + password
  auth_hash = base64.b64encode(token.encode('ascii')).decode()

  if config['modem_new_auth']:
    auth_url = url + '?login_' + auth_hash
  else:
    auth_url = url + '?' + auth_hash

  logging.debug('auth_hash: %s', auth_hash)
  logging.debug('auth_url: %s', auth_url)

  # This is going to respond with our "credential", which is a hash that we
  # have to send as a cookie with subsequent requests
  try:
    if config['modem_new_auth']:
      resp = requests.get(
        auth_url,
        headers={'Authorization': 'Basic ' + auth_hash},
        verify=verify_ssl,
        timeout=config['request_timeout']
      )
      cookie = resp.cookies['sessionId']
      logging.debug('cookie: %s', cookie)
    else:
      resp = requests.get(
        auth_url,
        auth=(username, password),
        verify=verify_ssl,
        timeout=config['request_timeout']
      )
      cookie = None

    if resp.status_code != 200:
      logging.error('Error authenticating with %s', url)
      logging.error('Status code: %s', resp.status_code)
      logging.error('Reason: %s', resp.reason)
      resp.close()
      return None

    token = resp.text
    resp.close()
  except Exception as exception:
    logging.error(exception)
    logging.error('Error authenticating with %s', url)
    return None

  if 'Password:' in token:
    logging.error('Authentication error, received login page.')
    return None

  return { 'token': token, 'cookie': cookie }


def get_html(config, credential):
  """ Get the status page from the modem
    return the raw html
  """

  if config["modem_ssl"]:
    init_url = f"https://{config['modem_ip']}/cmconnectionstatus.html"
  else:
    init_url = f"http://{config['modem_ip']}/cmconnectionstatus.html"

  if config['modem_auth_required'] and config['modem_new_auth']:
    url = init_url + '?ct_' + credential['token']
  else:
    url = init_url

  logging.debug('url: %s', url)

  verify_ssl = config['modem_verify_ssl']

  if config['modem_auth_required'] and not config['modem_new_auth']:
    cookies = { 'credential': credential['token'] }
  elif config['modem_auth_required'] and config['modem_new_auth']:
    cookies = { 'sessionId': credential['cookie'] }
  else:
    cookies = None

  logging.info('Retreiving stats from %s', init_url)

  try:
    resp = requests.get(
      url,
      cookies=cookies,
      verify=verify_ssl,
      timeout=config['request_timeout']
    )
    if resp.status_code != 200:
      logging.error('Error retreiving html from %s', url)
      logging.error('Status code: %s', resp.status_code)
      logging.error('Reason: %s', resp.reason)
      return None
    status_html = resp.content.decode("utf-8")
    resp.close()
  except Exception as exception:
    logging.error(exception)
    logging.error('Error retreiving html from %s', url)
    return None

  if 'Password:' in status_html:
    logging.error('Authentication error, received login page.')
    if not config['modem_auth_required']:
      logging.warning('You have modem_auth_required to False, but a login page was detected!')
    return None

  return status_html


def parse_html(html):
  """ Parse the HTML into the modem stats dict """
  logging.info('Parsing HTML for modem model sb8200')

  # As of Aug 2019 the SB8200 has a bug in its HTML
  # The tables have an extra </tr> in the table headers, we have to remove it so
  # that Beautiful Soup can parse it
  # Before: <tr><th colspan=7><strong>Upstream Bonded Channels</strong></th></tr>
  # After: <tr><th colspan=7><strong>Upstream Bonded Channels</strong></th>
  html = html.replace('Bonded Channels</strong></th></tr>', 'Bonded Channels</strong></th>', 2)

  soup = BeautifulSoup(html, 'html.parser')
  stats = {}

  # downstream table
  stats['downstream'] = []
  for table_row in soup.find_all("table")[1].find_all("tr"):
    if table_row.th:
      continue

    channel_id = table_row.find_all('td')[0].text.strip()

    # Some firmwares have a header row not already skiped by "if table_row.th", skip it if channel_id isn't an integer
    if not channel_id.isdigit():
      continue

    modulation = table_row.find_all('td')[2].text.replace("Other", "OFDM PLC").strip()
    frequency = table_row.find_all('td')[3].text.replace(" Hz", "").strip()
    power = table_row.find_all('td')[4].text.replace(" dBmV", "").strip()
    snr = table_row.find_all('td')[5].text.replace(" dB", "").strip()
    corrected = table_row.find_all('td')[6].text.strip()
    uncorrectables = table_row.find_all('td')[7].text.strip()

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
    logging.error('Failed to get any downstream stats! Probably a parsing issue in parse_html()')

  # upstream table
  stats['upstream'] = []
  for table_row in soup.find_all("table")[2].find_all("tr"):
    if table_row.th:
      continue

    # Some firmwares have a header row not already skiped by "if table_row.th", skip it if channel_id isn't an integer
    if not channel_id.isdigit():
      continue

    channel_id = table_row.find_all('td')[1].text.strip()
    channel_type = table_row.find_all('td')[3].text.replace(" Upstream", "").replace("OFDM", "OFDMA").strip()
    frequency = table_row.find_all('td')[4].text.replace(" Hz", "").strip()
    width = table_row.find_all('td')[5].text.replace(" Hz", "").strip()
    power = table_row.find_all('td')[6].text.replace(" dBmV", "").strip()

    stats['upstream'].append({
      'channel_id': channel_id,
      'channel_type': channel_type,
      'frequency': frequency,
      'width': width,
      'power': power,
    })

  logging.debug('upstream stats: %s', stats['upstream'])
  if not stats['upstream']:
    logging.error('Failed to get any upstream stats! Probably a parsing issue in parse_html()')

  return stats
