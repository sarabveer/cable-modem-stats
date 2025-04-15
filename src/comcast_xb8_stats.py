"""
  Pull stats from Comcast XB8
"""
# pylint: disable=line-too-long

import logging
import requests
from bs4 import BeautifulSoup

def get_credential(config):
  """ Get the cookie credential by posting the
    username and password.
  """
  logging.info('Obtaining login session from modem')

  url = f"http://{config['modem_ip']}/check.jst"

  logging.debug('login url: %s', url)

  data = {
    'username': config['modem_username'],
    'password': config['modem_password'],
    'locale': False
  }

  try:
    resp = requests.post(
      url,
      data=data,
      allow_redirects=False,
      timeout=config['request_timeout']
    )
    cookies = resp.cookies

    if resp.status_code != 302:
      logging.error('Error authenticating with %s', url)
      logging.error('Status code: %s', resp.status_code)
      logging.error('Reason: %s', resp.reason)
      resp.close()
      return None
    
    resp.close()
  except Exception as exception:
    logging.error(exception)
    logging.error('Error authenticating with %s', url)
    return None

  return cookies

def get_html(config, cookies):
  """ Get the status page from the modem
    return the raw html
  """

  url = f"http://{config['modem_ip']}/network_setup.jst"

  logging.info('Retreiving stats from %s', url)

  try:
    resp = requests.get(url, cookies=cookies, timeout=config['request_timeout'])
    if resp.status_code != 200:
      logging.error('Error retreiving html from %s', url)
      logging.error('Status code: %s', resp.status_code)
      logging.error('Reason: %s', resp.reason)
      resp.close()
      return None
    status_html = resp.content.decode("utf-8")
    resp.close()
  except Exception as exception:
    logging.error(exception)
    logging.error('Error retreiving html from %s', url)
    return None

  return status_html


def parse_html(html):
  """ Parse the HTML into the modem stats dict """
  logging.info('Parsing HTML for modem model xb8')

  soup = BeautifulSoup(html, 'html.parser')
  stats = {}

  # downstream table
  downstream_rows = soup.find_all("table")[0].find('tbody').find_all("tr")
  # Get count of downstream columns
  downstream_channels = len(downstream_rows[0].find_all("td"))
  stats['downstream'] = {}
  for i in range(downstream_channels):
    channel_id = downstream_rows[0].find_all("td")[i].text.strip()
    channel = {
      'channel_id': channel_id,
      'snr': downstream_rows[3].find_all("td")[i].text.replace(" dB", "").strip(),
      'power': downstream_rows[4].find_all("td")[i].text.replace(" dBmV", "").strip(),
    }

    # Modulation naming is a bit different for the xb8 than arris
    modulation = downstream_rows[5].find_all("td")[i].text.strip()
    if modulation == "OFDM":
      channel['modulation'] = "OFDM PLC"
    elif modulation == "256 QAM":
      channel['modulation'] = "QAM256"
    else:
      channel['modulation'] = modulation

    frequency = downstream_rows[2].find_all("td")[i].text.strip()
    if "MHz" in frequency:
      channel['frequency'] = frequency.replace(" MHz", "") + '000000'
    else:
      channel['frequency'] = frequency

    stats['downstream'][channel_id] = channel

  if not stats['downstream']:
    logging.error('Failed to get any downstream stats! Probably a parsing issue in parse_html()')

  # Parse Downstream Codeword stats table
  codeword_rows = soup.find_all("table")[2].find('tbody').find_all("tr")
  for i, element in enumerate(codeword_rows[0].find_all("td")):
     channel_id = element.text.strip()
     # NOTE: Indexing by channel_id is important as this table might be ordered
     #       differently than the "Channel Bonding" table parsed above.
     channel = stats['downstream'][channel_id]
     channel['unerrored'] = codeword_rows[1].find_all("td")[i].text.strip()
     channel['corrected'] = codeword_rows[2].find_all("td")[i].text.strip()
     channel['uncorrectables'] = codeword_rows[3].find_all("td")[i].text.strip()

  logging.debug('downstream stats: %s', stats['downstream'])

  # Convert downstream dictionary format to expected array format
  stats['downstream'] = stats['downstream'].values()

  # Upstream table
  upstream_rows = soup.find_all("table")[1].find('tbody').find_all("tr")
  # Get count of upstream columns
  upstream_channels = len(upstream_rows[0].find_all("td"))
  stats['upstream'] = []
  for i in range(upstream_channels):
    channel = {
      'channel_id': upstream_rows[0].find_all("td")[i].text.strip(),
      'frequency': upstream_rows[2].find_all("td")[i].text.replace(" MHz", "").strip() + '000000',
      # This symbol rate, not width. In ksym/sec rather than MHz.
      'width': upstream_rows[3].find_all("td")[i].text.strip(),
      'power': upstream_rows[4].find_all("td")[i].text.replace(" dBmV", "").strip(),
    }

    # Modulation naming is a bit different for the xb8 than arris
    channel_type = upstream_rows[5].find_all("td")[i].text.strip() + '-' + upstream_rows[6].find_all("td")[i].text.strip()
    if channel_type == "OFDMA-TDMA":
      channel['channel_type'] = "OFDMA"
    elif channel_type == "QAM-ATDMA":
      channel['channel_type'] = "SC-QAM"
    else:
      channel['channel_type'] = channel_type

    stats['upstream'].append(channel)

  logging.debug('upstream stats: %s', stats['upstream'])
  if not stats['upstream']:
    logging.error('Failed to get any upstream stats! Probably a parsing issue in parse_html()')

  return stats
