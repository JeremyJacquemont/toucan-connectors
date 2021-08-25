import logging
from timeit import default_timer as timer

import pandas as pd
from pydantic import Field
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth

from toucan_connectors.toucan_connector import ToucanConnector, ToucanDataSource

logger = logging.getLogger(__name__)


class SpotifyDataSource(ToucanDataSource):
    # fields
    query: str = Field(
        'daft punk',
        placeholder='spotify-query',
        description='The search element we want to send to spotify and get results like the artist name',
    )
    type_data: str = Field(
        'track',
        placeholder='track / playlist /...',
        description="The type of data, you're fetching from spotify",
    )

    limit: int = Field(
        10,
        placeholder=10,
        description='The number of elements we want',
    )
    offset: int = Field(
        5,
        placeholder=5,
        description='The offset number of elements we want',
    )


class SpotifyConnector(ToucanConnector):
    name: str = Field(
        'Toucan Toco Spotify',
        title='Client ID',
        description='The name of the connector',
        **{'ui.required': True},
    )
    client_id: str = Field(
        '',
        title='Client ID',
        placeholder='9dc5eae093274640ba537d928be0db63',
        description='The client id of your Spotify application',
        **{'ui.required': True},
    )
    client_secret: str = Field(
        '',
        title='Client Secret',
        placeholder='8c3d809636d54b8db7f83e178accc0a7',
        description='The client secret of your Spotify application',
        **{'ui.required': True},
    )
    scope: str = Field(
        'user-read-private',
        Title='Scope',
        description='The scope the integration',
        placeholder='user-read-private',
    )
    authorization_url: str = Field('https://accounts.spotify.com/authorize', **{'ui_hidden': True})
    token_url: str = Field('https://accounts.spotify.com/api/token', **{'ui_hidden': True})
    auth_flow_id: str = Field(None, **{'ui_hidden': True})
    oauth2_version = Field('2', **{'ui_hidden': True})
    redirect_uri: str = Field(
        None, description='The redirect uri link', placeholder='https://toucantoco.com/webhook'
    )

    data_source_model: SpotifyDataSource
    connection_object: SpotifyOAuth = None

    def build_authorization_url(self, **kwargs):
        return self.connection_object.get_authorize_url(kwargs)

    def retrieve_tokens(self):
        return self.get_access_token()

    def get_access_token(self):
        logger.info('[-] Get access token from Spotify API')
        connection_start = timer()

        token = self.connection_object.get_cached_token()
        if not self.connection_object.validate_token(token):
            token = self.connection_object.get_access_token(
                code=self.connection_object.get_authorization_code(
                    response=self.connection_object.get_auth_response(open_browser=True)
                )
            )
        connection_end = timer()

        logger.info(
            f'[benchmark][spotify] - get_access_token {connection_end - connection_start} seconds',
            extra={
                'benchmark': {
                    'operation': 'get_access_token',
                    'execution_time': connection_end - connection_start,
                    'connector': 'spotify',
                }
            },
        )

        return token

    # To maintain a connection
    def connect(self):
        logger.info('[-] Connect at Spotify API')

        connection_start = timer()
        self.connection_object = SpotifyOAuth(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
            scope=self.scope,
        )
        connection_end = timer()

        logger.info(
            f'[benchmark][spotify] - connect {connection_end - connection_start} seconds',
            extra={
                'benchmark': {
                    'operation': 'connect',
                    'execution_time': connection_end - connection_start,
                    'connector': 'spotify',
                }
            },
        )

    def _retrieve_data(self, data_source: SpotifyDataSource) -> pd.DataFrame:
        logger.info('[-] Fetching results from Spotify API')
        query_start = timer()
        logger.info(
            f'[-] query : {data_source.query},\n'
            f'[-] type : {data_source.type},\n'
            f'[-] limit : {data_source.limit},\n'
            f'[-] offset : {data_source.offset}'
        )
        results = pd.DataFrame(
            Spotify(auth_manager=self.connection_object).search(
                q=data_source.query,
                type=data_source.type_data,
                limit=data_source.limit,
                offset=data_source.offset,
            )
        )
        query_end = timer()

        logger.info(
            f'[benchmark][spotify] - quering {query_end - query_start} seconds',
            extra={
                'benchmark': {
                    'operation': 'quering',
                    'execution_time': query_end - query_start,
                    'connector': 'spotify',
                }
            },
        )

        return results
