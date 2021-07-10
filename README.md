# arris_cable_modem_stats

This is a Python script to scrape stats from the Arris SB8200 cable modem web interface. Results are meant to be sent to InfluxDB 2.x for use with Grafana, but other targets could be added.

Credit goes to:
- https://github.com/andrewfraley/arris_cable_modem_stats
- https://github.com/billimek/SB6183-stats-for-influxdb


## Authentication

In late Oct 2020, Comcast deployed firmware updates to the SB8200 which now require authenticating against the modem. If your modem requires authentication (you get a login page when browsing to https://192.168.100.1/), then you must edit your config.ini file (or set the matching ENV variables) and set ```modem_auth_required``` to ```True```, and set ```modem_password``` appropriately. By default, your modem's password is the last eight characters of the serial number, located on a sticker on the bottom of the modem.

There is some kind of bug (at least with Comcast's firmware) where the modem cannot handle more than ~10 sessions. Once those sessions have been used up, it seems you must wait for them to expire or reboot the modem. I have not been able to successfully log out of the sessions, but this script attempts to keep reusing the same session as long as it can.

## Run in Docker
Run in a Docker container with:

```bash
docker build -t arris_stats .
docker run arris_stats
```

Note that the same parameters from config.ini can be set as ENV variables, ENV overrides config.ini.

## Run Locally

- Install Python 3.8.x or later
- Clone repo
- Change directory
  - `$ cd arris_cable_modem_stats/src`

- Install virtualenv
  - `$ python3 -m pip install virtualenv`

- Create and activate virtualenv
  - `$ python3 -m venv venv`
  - `$ source venv/bin/activate`

- Install pip dependencies
  - `python3 -m pip install -r requirements.txt`

- Edit config.ini and set the approriate settings

- If your cable modem requires authentication, edit config.ini and set:
  - `modem_auth_required = True`
  - `modem_password = <your-password>`

- Run arris_stats.py
  - `python3 arris_stats.py --config config.ini`

## Config Settings
Config settings can be provided by the config.ini file, or set as ENV variables. ENV variables override config.ini. This is useful when running in a Docker container.

| Option | Default | Notes |
| ------------ | ------------ | ------------ |
| `arris_stats_debug` | `False` | enables debug logs |
| `destination` | influxdb | influxdb is the only valid option at this time |
| `sleep_interval` | 300 | |
| `modem_url` | https://192.168.100.1/cmconnectionstatus.html | |
| `modem_verify_ssl` | `False` | |
| `modem_auth_required` | `False` | |
| `modem_username` | admin | |
| `modem_password` | `None` | |
| `modem_model` | sb8200 | only sb8200 is supported at this time |
| `exit_on_auth_error` | `True` | Any auth error will cause an exit, useful when running in a Docker container to get a new session |
| `exit_on_html_error` | `True` | Any error retrieving the html will cause an exit, mostly redundant with exit_on_auth_error |
| `clear_auth_token_on_html_error` | `True` | This is useful if you don't want to exit, but do want to get a new session if/when getting the stats fails |
| `sleep_before_exit` | `True` | If you want to sleep before exiting on errors, useful for Docker container when you have `restart = always` |
| `influx_url` | http://localhost:8086 | |
| `influx_bucket` | cable_modem_stats | |
| `influx_org` | `None` | |
| `influx_token` | `None` | |
| `influx_verify_ssl` | `True` | |

### Debugging

You can enable debug logs in three ways:

1. Use --debug when running from cli
  - `pipenv run python3 sb8200_stats.py --debug --config config.ini`
2. Set ENV variable `arris_stats_debug = true`
3. Set config.ini `arris_stats_debug = true`

## InfluxDB

The Grafana dashboard uses InfluxQL, so a DBRP mapping needs to be made:

```bash
influx v1 dbrp create \
  --db cable_modem_stats \
  --rp cable_modem_stats \
  --bucket-id <bucket-id> \
  --default
```

Replace `<bucket-id>` with the ID of the `cable_modem_stats` bucket created in InfluxDB 2.x

Read more about this [here](https://docs.influxdata.com/influxdb/v2.0/query-data/influxql/)

## Grafana

In order to add the InfluxDB data source to Grafana, a DBRP has to be created (as shown above), and then the data source has to be setup as shown below:

![Influx Grafana Data Source](readme/grafana_influx.png)

The `Authorization` header has to be in format: `Token <your-token-here>`

Read more about this [here](https://github.com/grafana/grafana/issues/29372#issuecomment-733717988).

### Arris SB8200 Dashboard

- Setup arrris_stats.py to run from somewhere
- Import a new dashboard using the [grafana/sb8200_grafana.json](grafana/sb8200_grafana.json) file. Originally exported from Grafana v8.0.5

![SB8200 Dashboard 1](readme/dash1.png)
![SB8200 Dashboard 2](readme/dash2.png)
