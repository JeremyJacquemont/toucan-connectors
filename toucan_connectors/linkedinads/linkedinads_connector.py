"""LinkedinAds connector"""
import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Type

import pandas as pd
import requests
from pydantic import Field

from toucan_connectors.common import ConnectorStatus, FilterSchema, HttpError, transform_with_jq
from toucan_connectors.oauth2_connector.oauth2connector import (
    OAuth2Connector,
    OAuth2ConnectorConfig,
)
from toucan_connectors.toucan_connector import (
    ConnectorSecretsForm,
    ToucanConnector,
    ToucanDataSource,
)

AUTHORIZATION_URL: str = 'https://www.linkedin.com/oauth/v2/authorization'
SCOPE: str = 'r_organization_social,r_ads_reporting,r_ads'
TOKEN_URL: str = 'https://www.linkedin.com/oauth/v2/accessToken'


class FinderMethod(str, Enum):
    analytics = 'analytics'
    statistics = 'statistics'


class TimeGranularity(str, Enum):
    # https://docs.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/ads-reporting#query-parameters
    all = 'ALL'
    daily = 'DAILY'
    monthly = 'MONTHLY'
    yearly = 'YEARLY'


class NoCredentialsError(Exception):
    """Raised when no secrets available."""


class LinkedinadsDataSource(ToucanDataSource):
    """
    LinkedinAds data source class.
    """

    finder_methods: FinderMethod = Field(
        FinderMethod.analytics, title='Finder methods', description='Default: analytics'
    )
    start_date: str = Field(..., title='Start date', description='Start date of the dataset')
    end_date: str = Field(
        None, title='End date', description='End date of the dataset, optional & default to today'
    )
    time_granularity: TimeGranularity = Field(
        TimeGranularity.all,
        title='Time granularity',
        description='Granularity of the dataset, default all result grouped',
    )
    filter: str = (
        FilterSchema  # TODO to remove once json unnesting will be available in postprocess
    )
    parameters: dict = Field(
        None,
        description='See https://docs.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/ads-reporting for more information',
    )

    class Config:
        @staticmethod
        def schema_extra(schema: Dict[str, Any], model: Type['LinkedinadsDataSource']) -> None:
            keys = schema['properties'].keys()
            prio_keys = [
                'finder_methods',
                'start_date',
                'end_date',
                'time_granularity',
                'filter',
                'parameters',
            ]
            new_keys = prio_keys + [k for k in keys if k not in prio_keys]
            schema['properties'] = {k: schema['properties'][k] for k in new_keys}


class LinkedinadsConnector(ToucanConnector):
    """The LinkedinAds connector."""

    data_source_model: LinkedinadsDataSource
    _auth_flow = 'oauth2'
    auth_flow_id: Optional[str]
    _baseroute = 'https://api.linkedin.com/v2/adAnalyticsV2?q='

    @staticmethod
    def get_connector_secrets_form() -> ConnectorSecretsForm:
        return ConnectorSecretsForm(
            documentation_md=(Path(os.path.dirname(__file__)) / 'doc.md').read_text(),
            secrets_schema=OAuth2ConnectorConfig.schema(),
        )

    def __init__(self, **kwargs):
        super().__init__(
            **{k: v for k, v in kwargs.items() if k not in OAuth2Connector.init_params}
        )
        # we use __dict__ so that pydantic does not complain about the _oauth2_connector field
        self.__dict__['_oauth2_connector'] = OAuth2Connector(
            auth_flow_id=self.auth_flow_id,
            authorization_url=AUTHORIZATION_URL,
            scope=SCOPE,
            token_url=TOKEN_URL,
            redirect_uri=kwargs['redirect_uri'],
            config=OAuth2ConnectorConfig(
                client_id=kwargs['client_id'],
                client_secret=kwargs['client_secret'],
            ),
            secrets_keeper=kwargs['secrets_keeper'],
        )

    def build_authorization_url(self, **kwargs):
        return self.__dict__['_oauth2_connector'].build_authorization_url(**kwargs)

    def retrieve_tokens(self, authorization_response: str):
        return self.__dict__['_oauth2_connector'].retrieve_tokens(authorization_response)

    def get_access_token(self):
        return self.__dict__['_oauth2_connector'].get_access_token()

    def _retrieve_data(self, data_source: LinkedinadsDataSource) -> pd.DataFrame:
        """
        Point of entry for data retrieval in the connector

        Requires:
        - Datasource
        - Secrets
        """
        # Retrieve the access token
        access_token = self.get_access_token()
        if not access_token:
            raise NoCredentialsError('No credentials')
        headers = {'Authorization': f'Bearer {access_token}'}

        # Parse provided dates
        splitted_start = data_source.start_date.split('/')
        start_day, start_month, start_year = (
            int(splitted_start[0]),
            int(splitted_start[1]),
            int(splitted_start[2]),
        )

        # Build the query, 1 mandatory parameters
        query = (
            f'dateRange.start.day={start_day}&dateRange.start.month={start_month}'
            f'&dateRange.start.year={start_year}&timeGranularity={data_source.time_granularity}'
        )

        if data_source.end_date:
            splitted_end = data_source.end_date.split('/')
            end_day, end_month, end_year = (
                int(splitted_end[0]),
                int(splitted_end[1]),
                int(splitted_end[2]),
            )
            query += f'&dateRange.end.day={end_day}&dateRange.end.month={end_month}&dateRange.end.year={end_year}'

        # Build the query, 2 optional array parameters
        if data_source.parameters:
            for p in data_source.parameters.keys():
                query += f'&{p}={data_source.parameters.get(p)}'

        # Get the data
        res = requests.get(
            url=f'{self._baseroute}{data_source.finder_methods}', params=query, headers=headers
        )

        try:
            assert res.ok
            data = res.json()

        except AssertionError:
            raise HttpError(res.text)

        jqfilter = data_source.filter
        try:
            return pd.DataFrame(transform_with_jq(data, jqfilter))
        except ValueError:
            LinkedinadsConnector.logger.error(f'Could not transform {data} using {jqfilter}')

    def get_status(self) -> ConnectorStatus:
        """
        Test the Google Sheets connexion.

        If successful, returns a message with the email of the connected user account.
        """
        try:
            access_token = self.get_access_token()
        except Exception:
            return ConnectorStatus(status=False, error='Credentials are missing')

        if not access_token:
            return ConnectorStatus(status=False, error='Credentials are missing')

        return ConnectorStatus(status=True, message='Connector status OK')
