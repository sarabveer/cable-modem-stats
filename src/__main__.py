"""
  Pull stats from Arris Cable modem's web interface
  Send stats to InfluxDB

  https://github.com/andrewfraley/arris_cable_modem_stats
"""
# pylint: disable=line-too-long

import os
import sys
import time
import logging
import argparse
import configparser
from datetime import datetime, UTC
import urllib3

def main():
  """ MAIN """
  args = get_args()
  init_logger(args.debug)

  config_path = args.config
  config = get_config(config_path)

  # Re-init the logger if we set enable_debug in ENV or config.ini
  if config['enable_debug']:
    init_logger(True)

  sleep_interval = int(config['sleep_interval'])
  destination = config['destination']
  modem_model = config['modem_model']

  if modem_model == 'sb8200':
    import arris_stats_sb8200
    get_credential = arris_stats_sb8200.get_credential
    get_data = arris_stats_sb8200.get_html
    parse_data = arris_stats_sb8200.parse_html
  elif modem_model == 's33':
    import arris_stats_s33
    get_credential = arris_stats_s33.get_credential
    get_data = arris_stats_s33.get_json
    parse_data = arris_stats_s33.parse_json
  elif modem_model == 'xb8':
    import comcast_xb8_stats
    get_credential = comcast_xb8_stats.get_credential
    get_data = comcast_xb8_stats.get_html
    parse_data = comcast_xb8_stats.parse_html
  else:
    error_exit('Modem model %s not supported!  Aborting', sleep=False)

  # Disable the SSL warnings if we're not verifying SSL
  if not config['modem_verify_ssl']:
    urllib3.disable_warnings()

  credential = None

  first = True
  while True:
    if not first:
      logging.info('Sleeping for %s seconds', sleep_interval)
      sys.stdout.flush()
      time.sleep(sleep_interval)
    first = False

    if config['modem_auth_required'] or modem_model == 's33' or modem_model == 'xb8':
      while not credential:
        credential = get_credential(config)
        if not credential and config['exit_on_auth_error']:
          error_exit('Unable to authenticate with modem. Exiting since exit_on_auth_error is True.', config)
        if not credential:
          logging.info('Unable to obtain valid login session, sleeping for: %ss', sleep_interval)
          time.sleep(sleep_interval)
          continue

    # Get the HTML from the modem
    data = get_data(config, credential)
    if not data:
      if config['exit_on_html_error']:
        error_exit('No data obtained from modem. Exiting since exit_on_html_error is True.', config)
      
      logging.error('No data to parse, giving up until next interval.')
      if config['clear_auth_token_on_html_error']:
        logging.info('clear_auth_token_on_html_error is true, clearing credential token.')
        credential = None
      continue

    # Parse the HTML to get our stats
    stats = parse_data(data)

    if not stats or (not stats['upstream'] and not stats['downstream']):
      logging.error(
        'Failed to get any stats, giving up until next interval')
      continue

    # Where should 6we send the results?
    if destination == 'influxdb':
      send_to_influx(stats, config)
    else:
      error_exit('Destination %s not supported!  Aborting.' % destination, sleep=False)


def get_args():
  """ Get argparser args """
  parser = argparse.ArgumentParser()
  parser.add_argument('--config', metavar='config_file_path', help='Path to config file', required=True)
  parser.add_argument('--debug', help='Enable debug logging', action='store_true', required=False, default=False)
  args = parser.parse_args()
  return args

def get_config(config_path=None):
  """ Grab config from the ini config file,
    then grab the same variables from ENV to override
  """

  default_config = {
    # Main
    'enable_debug': False,
    'destination': 'influxdb',
    'sleep_interval': 120,
    'modem_ip': '192.168.100.1',
    'modem_verify_ssl': False,
    'modem_username': 'admin',
    'modem_password': None,
    'modem_model': 's33',
    'exit_on_auth_error': True,
    'exit_on_html_error': True,
    'clear_auth_token_on_html_error': True,
    'sleep_before_exit': True,
    'request_timeout': 30,

    # SB8200 Only
    'modem_ssl': False,
    'modem_auth_required': False,
    'modem_new_auth': False,

    # InfluxDB
    'influx_url': 'http://localhost:8086',
    'influx_bucket': 'cable_modem_stats',
    'influx_org': None,
    'influx_token': None,
    'influx_verify_ssl': True,
  }

  config = default_config.copy()

  # Get config from config.ini first
  if config_path:
    # Some hacky action to get the config without using section headings in the file
    # https://stackoverflow.com/a/10746467/866057
    parser = configparser.RawConfigParser()
    section = 'MAIN'
    with open(config_path) as f:
      file_content = '[%s]\n' % section + f.read()
    parser.read_string(file_content)

    for param in default_config:
      config[param] = parser[section].get(param, default_config[param])

  # Get it from ENV now and override anything we find
  for param in config:
    if os.environ.get(param):
      config[param] = os.environ.get(param)

  # Special handling depending ontype
  for param in config:
    # If the default value is a boolean, but we have a string, convert it
    if isinstance(default_config[param], bool) and isinstance(config[param], str):
      config[param] = str_to_bool(string=config[param], name=param)

    # If the default value is an int, but we have a string, convert it
    if isinstance(default_config[param], int) and isinstance(config[param], str):
      config[param] = int(config[param])

    # Finally any 'None' string should just be None
    if default_config[param] is None and config[param] == 'None':
      config[param] = None

  return config

def send_to_influx(stats, config):
  """ Send the stats to InfluxDB """
  logging.info('Sending stats to InfluxDB (%s)', config['influx_url'])

  from influxdb_client import InfluxDBClient, Point
  from influxdb_client.client.write_api import SYNCHRONOUS

  influx_client = InfluxDBClient(
    url = config['influx_url'],
    token = config['influx_token'],
    org = config['influx_org'],
    verify_ssl = config['influx_verify_ssl']
  )
  write_api = influx_client.write_api(write_options = SYNCHRONOUS)

  series = []
  current_time = datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')

  for stats_down in stats['downstream']:
    data = {
      'measurement': 'downstream_statistics',
      'time': current_time,
      'fields': {
        'frequency': int(float(stats_down['frequency'])),
        'power': float(stats_down['power']),
        'snr': float(stats_down['snr']),
        'corrected': int(stats_down['corrected']),
        'uncorrectables': int(stats_down['uncorrectables'])
      },
      'tags': {
        'channel_id': int(stats_down['channel_id']),
        'modulation': stats_down['modulation']
      }
    }
    ## Only some modems, like the XB8, has the 'unerrored' value
    if 'unerrored' in stats_down:
      data['fields']['unerrored'] = int(stats_down['unerrored'])

    series.append(Point.from_dict(data))

  for stats_up in stats['upstream']:
    series.append(Point.from_dict({
      'measurement': 'upstream_statistics',
      'time': current_time,
      'fields': {
        'frequency': int(float(stats_up['frequency'])),
        'power': float(stats_up['power']),
        'width': int(stats_up['width']),
      },
      'tags': {
        'channel_id': int(stats_up['channel_id']),
        'channel_type': stats_up['channel_type']
      }
    }))

  try:
    write_api.write(bucket = config['influx_bucket'], record = series)
  except Exception:
    logging.exception('Failed To Write To InfluxDB')
    return

  logging.info('Successfully wrote data to InfluxDB')
  logging.debug('Influx series sent to db:')
  logging.debug(series)

def error_exit(message, config=None, sleep=True):
  """ Log error, sleep if needed, then exit 1 """
  logging.error(message)
  if sleep and config and config['sleep_before_exit']:
    logging.info('Sleeping for %s seconds before exiting since sleep_before_exit is True', config['sleep_interval'])
    time.sleep(config['sleep_interval'])
  sys.exit(1)

def str_to_bool(string, name):
  """ Return True is string ~= 'true' """
  if string.lower() == 'true':
    return True
  if string.lower() == 'false':
    return False

  raise ValueError('Config parameter % s should be boolean "true" or "false", but value is neither of those.' % name)

def init_logger(debug=False):
  """ Start the python logger """
  log_format = '%(asctime)s %(levelname)-8s %(message)s'

  if debug:
    level = logging.DEBUG
  else:
    level = logging.INFO

  # https://stackoverflow.com/a/61516733/866057
  try:
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_handler = root_logger.handlers[0]
    root_handler.setFormatter(logging.Formatter(log_format))
  except IndexError:
    logging.basicConfig(level=level, format=log_format)

if __name__ == '__main__':
  main()
