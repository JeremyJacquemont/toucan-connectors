import socket
import time
from contextlib import suppress
from os import environ, getenv, path
from typing import Any

import pytest
import yaml
from docker import APIClient
from docker.tls import TLSConfig
from slugify import slugify

from toucan_connectors.oauth2_connector.oauth2connector import SecretsKeeper


def pytest_addoption(parser):
    parser.addoption('--pull', action='store_true', default=False, help='Pull docker images')


@pytest.fixture(scope='session')
def docker_pull(request):
    return request.config.getoption('--pull')


@pytest.fixture(scope='session')
def docker():
    docker_kwargs = {'version': 'auto'}
    if 'DOCKER_HOST' in environ:
        docker_kwargs['base_url'] = environ['DOCKER_HOST']
    if environ.get('DOCKER_TLS_VERIFY', 0) == '1':
        docker_kwargs['tls'] = TLSConfig(
            (f"{environ['DOCKER_CERT_PATH']}/cert.pem", f"{environ['DOCKER_CERT_PATH']}/key.pem")
        )
    return APIClient(**docker_kwargs)


@pytest.fixture(scope='session')
def unused_port():
    def f():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]

    return f


def wait_for_container(checker_callable, host_port, image, skip_exception=None, timeout=60):
    skip_exception = skip_exception or Exception
    for i in range(timeout):
        try:
            checker_callable(host_port)
            break
        except skip_exception as e:
            print(f'Waiting for image to start...(last exception: {e})')
            time.sleep(1)
    else:
        pytest.fail(f'Cannot start {image} server')


@pytest.fixture(scope='module')
def container_starter(request, docker, docker_pull):
    def f(
        image,
        internal_port,
        host_port,
        env=None,
        volumes=None,
        command=None,
        checker_callable=None,
        skip_exception=None,
        timeout=None,
    ):

        if docker_pull:
            print(f'Pulling {image} image')
            docker.pull(image)

        # Use in devcontainer to allow volumes access
        if getenv("LOCAL_WORKSPACE_FOLDER") is not None:
            volumes = [vol.replace('/workspaces/toucan-connectors/tests/.', f'{getenv("LOCAL_WORKSPACE_FOLDER")}/tests') for vol in volumes]

        host_config = docker.create_host_config(
            port_bindings={internal_port: host_port}, binds=volumes
        )

        if volumes is not None:
            volumes = [vol.split(':')[1] for vol in volumes]

        container_name = '-'.join(['toucan', slugify(image), 'server'])
        print(f'Creating {container_name} on port {host_port}')
        container = docker.create_container(
            image=image,
            name=container_name,
            ports=[internal_port],
            detach=True,
            environment=env,
            volumes=volumes,
            command=command,
            host_config=host_config,
        )

        print(f'Starting {container_name}')
        docker.start(container=container['Id'])

        def fin():
            print(f'Stopping {container_name}')
            docker.kill(container=container['Id'])
            print(f'Killing {container_name}')
            with suppress(Exception):
                docker.remove_container(container['Id'], v=True)

        request.addfinalizer(fin)
        container['port'] = host_port

        if checker_callable is not None:
            wait_for_container(checker_callable, host_port, image, skip_exception, timeout)
        return container

    return f


@pytest.fixture(scope='module')
def service_container(unused_port, container_starter):
    def f(service_name, checker_callable=None, skip_exception=None, timeout=60):
        with open(f'{path.dirname(__file__)}/docker-compose.yml') as docker_comppse_yml:
            docker_conf = yaml.load(docker_comppse_yml)
        service_conf = docker_conf[service_name]
        volumes = service_conf.get('volumes')
        if volumes is not None:
            volumes = [path.join(path.dirname(__file__), vol) for vol in volumes]
        params = {
            'image': service_conf['image'],
            'internal_port': service_conf['ports'][0].split(':')[0],
            'host_port': unused_port(),
            'env': service_conf.get('environment'),
            'volumes': volumes,
            'command': service_conf.get('command'),
            'timeout': timeout,
            'checker_callable': checker_callable,
            'skip_exception': skip_exception,
        }

        return container_starter(**params)

    return f


@pytest.fixture
def bearer_api_key():
    bearer_api_key = getenv('BEARER_API_KEY')
    if not bearer_api_key:
        pytest.skip("'BEARER_API_KEY' is not set")
    return bearer_api_key


@pytest.fixture
def bearer_aircall_auth_id(bearer_api_key):
    bearer_aircall_auth_id = getenv('BEARER_AIRCALL_AUTH_ID')
    if not bearer_aircall_auth_id:
        pytest.skip("'BEARER_AIRCALL_AUTH_ID' is not set")
    return bearer_aircall_auth_id


@pytest.fixture
def secrets_keeper():
    class SimpleSecretsKeeper(SecretsKeeper):
        def __init__(self):
            self.store = {}

        def load(self, key: str) -> Any:
            if key not in self.store:
                return None
            return self.store[key]

        def save(self, key: str, value: Any):
            self.store[key] = value

    return SimpleSecretsKeeper()


@pytest.fixture
def wsdl_sample():
    return """<?xml version="1.0" encoding="UTF-8"?><definitions xmlns="http://schemas.xmlsoap.org/wsdl/" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/" xmlns:soap12="http://schemas.xmlsoap.org/wsdl/soap12/" xmlns:tns="http://www.oorsprong.org/websamples.countryinfo" name="CountryInfoService" targetNamespace="http://www.oorsprong.org/websamples.countryinfo"><types><xs:schema elementFormDefault="qualified" targetNamespace="http://www.oorsprong.org/websamples.countryinfo"><xs:complexType name="tContinent"><xs:sequence><xs:element name="sCode" type="xs:string"/><xs:element name="sName" type="xs:string"/></xs:sequence></xs:complexType><xs:complexType name="tCurrency"><xs:sequence><xs:element name="sISOCode" type="xs:string"/><xs:element name="sName" type="xs:string"/></xs:sequence></xs:complexType><xs:complexType name="tCountryCodeAndName"><xs:sequence><xs:element name="sISOCode" type="xs:string"/><xs:element name="sName" type="xs:string"/></xs:sequence></xs:complexType><xs:complexType name="tCountryCodeAndNameGroupedByContinent"><xs:sequence><xs:element name="Continent" type="tns:tContinent"/><xs:element name="CountryCodeAndNames" type="tns:ArrayOftCountryCodeAndName"/></xs:sequence></xs:complexType><xs:complexType name="tCountryInfo"><xs:sequence><xs:element name="sISOCode" type="xs:string"/><xs:element name="sName" type="xs:string"/><xs:element name="sCapitalCity" type="xs:string"/><xs:element name="sPhoneCode" type="xs:string"/><xs:element name="sContinentCode" type="xs:string"/><xs:element name="sCurrencyISOCode" type="xs:string"/><xs:element name="sCountryFlag" type="xs:string"/><xs:element name="Languages" type="tns:ArrayOftLanguage"/></xs:sequence></xs:complexType><xs:complexType name="tLanguage"><xs:sequence><xs:element name="sISOCode" type="xs:string"/><xs:element name="sName" type="xs:string"/></xs:sequence></xs:complexType><xs:complexType name="ArrayOftCountryCodeAndName"><xs:sequence><xs:element name="tCountryCodeAndName" type="tns:tCountryCodeAndName" minOccurs="0" maxOccurs="unbounded" nillable="true"/></xs:sequence></xs:complexType><xs:complexType name="ArrayOftLanguage"><xs:sequence><xs:element name="tLanguage" type="tns:tLanguage" minOccurs="0" maxOccurs="unbounded" nillable="true"/></xs:sequence></xs:complexType><xs:complexType name="ArrayOftContinent"><xs:sequence><xs:element name="tContinent" type="tns:tContinent" minOccurs="0" maxOccurs="unbounded" nillable="true"/></xs:sequence></xs:complexType><xs:complexType name="ArrayOftCurrency"><xs:sequence><xs:element name="tCurrency" type="tns:tCurrency" minOccurs="0" maxOccurs="unbounded" nillable="true"/></xs:sequence></xs:complexType><xs:complexType name="ArrayOftCountryCodeAndNameGroupedByContinent"><xs:sequence><xs:element name="tCountryCodeAndNameGroupedByContinent" type="tns:tCountryCodeAndNameGroupedByContinent" minOccurs="0" maxOccurs="unbounded" nillable="true"/></xs:sequence></xs:complexType><xs:complexType name="ArrayOftCountryInfo"><xs:sequence><xs:element name="tCountryInfo" type="tns:tCountryInfo" minOccurs="0" maxOccurs="unbounded" nillable="true"/></xs:sequence></xs:complexType><xs:element name="ListOfContinentsByName"><xs:complexType><xs:sequence/></xs:complexType></xs:element><xs:element name="ListOfContinentsByNameResponse"><xs:complexType><xs:sequence><xs:element name="ListOfContinentsByNameResult" type="tns:ArrayOftContinent"/></xs:sequence></xs:complexType></xs:element><xs:element name="ListOfContinentsByCode"><xs:complexType><xs:sequence/></xs:complexType></xs:element><xs:element name="ListOfContinentsByCodeResponse"><xs:complexType><xs:sequence><xs:element name="ListOfContinentsByCodeResult" type="tns:ArrayOftContinent"/></xs:sequence></xs:complexType></xs:element><xs:element name="ListOfCurrenciesByName"><xs:complexType><xs:sequence/></xs:complexType></xs:element><xs:element name="ListOfCurrenciesByNameResponse"><xs:complexType><xs:sequence><xs:element name="ListOfCurrenciesByNameResult" type="tns:ArrayOftCurrency"/></xs:sequence></xs:complexType></xs:element><xs:element name="ListOfCurrenciesByCode"><xs:complexType><xs:sequence/></xs:complexType></xs:element><xs:element name="ListOfCurrenciesByCodeResponse"><xs:complexType><xs:sequence><xs:element name="ListOfCurrenciesByCodeResult" type="tns:ArrayOftCurrency"/></xs:sequence></xs:complexType></xs:element><xs:element name="CurrencyName"><xs:complexType><xs:sequence><xs:element name="sCurrencyISOCode" type="xs:string"/></xs:sequence></xs:complexType></xs:element><xs:element name="CurrencyNameResponse"><xs:complexType><xs:sequence><xs:element name="CurrencyNameResult" type="xs:string"/></xs:sequence></xs:complexType></xs:element><xs:element name="ListOfCountryNamesByCode"><xs:complexType><xs:sequence/></xs:complexType></xs:element><xs:element name="ListOfCountryNamesByCodeResponse"><xs:complexType><xs:sequence><xs:element name="ListOfCountryNamesByCodeResult" type="tns:ArrayOftCountryCodeAndName"/></xs:sequence></xs:complexType></xs:element><xs:element name="ListOfCountryNamesByName"><xs:complexType><xs:sequence/></xs:complexType></xs:element><xs:element name="ListOfCountryNamesByNameResponse"><xs:complexType><xs:sequence><xs:element name="ListOfCountryNamesByNameResult" type="tns:ArrayOftCountryCodeAndName"/></xs:sequence></xs:complexType></xs:element><xs:element name="ListOfCountryNamesGroupedByContinent"><xs:complexType><xs:sequence/></xs:complexType></xs:element><xs:element name="ListOfCountryNamesGroupedByContinentResponse"><xs:complexType><xs:sequence><xs:element name="ListOfCountryNamesGroupedByContinentResult" type="tns:ArrayOftCountryCodeAndNameGroupedByContinent"/></xs:sequence></xs:complexType></xs:element><xs:element name="CountryName"><xs:complexType><xs:sequence><xs:element name="sCountryISOCode" type="xs:string"/></xs:sequence></xs:complexType></xs:element><xs:element name="CountryNameResponse"><xs:complexType><xs:sequence><xs:element name="CountryNameResult" type="xs:string"/></xs:sequence></xs:complexType></xs:element><xs:element name="CountryISOCode"><xs:complexType><xs:sequence><xs:element name="sCountryName" type="xs:string"/></xs:sequence></xs:complexType></xs:element><xs:element name="CountryISOCodeResponse"><xs:complexType><xs:sequence><xs:element name="CountryISOCodeResult" type="xs:string"/></xs:sequence></xs:complexType></xs:element><xs:element name="CapitalCity"><xs:complexType><xs:sequence><xs:element name="sCountryISOCode" type="xs:string"/></xs:sequence></xs:complexType></xs:element><xs:element name="CapitalCityResponse"><xs:complexType><xs:sequence><xs:element name="CapitalCityResult" type="xs:string"/></xs:sequence></xs:complexType></xs:element><xs:element name="CountryCurrency"><xs:complexType><xs:sequence><xs:element name="sCountryISOCode" type="xs:string"/></xs:sequence></xs:complexType></xs:element><xs:element name="CountryCurrencyResponse"><xs:complexType><xs:sequence><xs:element name="CountryCurrencyResult" type="tns:tCurrency"/></xs:sequence></xs:complexType></xs:element><xs:element name="CountryFlag"><xs:complexType><xs:sequence><xs:element name="sCountryISOCode" type="xs:string"/></xs:sequence></xs:complexType></xs:element><xs:element name="CountryFlagResponse"><xs:complexType><xs:sequence><xs:element name="CountryFlagResult" type="xs:string"/></xs:sequence></xs:complexType></xs:element><xs:element name="CountryIntPhoneCode"><xs:complexType><xs:sequence><xs:element name="sCountryISOCode" type="xs:string"/></xs:sequence></xs:complexType></xs:element><xs:element name="CountryIntPhoneCodeResponse"><xs:complexType><xs:sequence><xs:element name="CountryIntPhoneCodeResult" type="xs:string"/></xs:sequence></xs:complexType></xs:element><xs:element name="FullCountryInfo"><xs:complexType><xs:sequence><xs:element name="sCountryISOCode" type="xs:string"/></xs:sequence></xs:complexType></xs:element><xs:element name="FullCountryInfoResponse"><xs:complexType><xs:sequence><xs:element name="FullCountryInfoResult" type="tns:tCountryInfo"/></xs:sequence></xs:complexType></xs:element><xs:element name="FullCountryInfoAllCountries"><xs:complexType><xs:sequence/></xs:complexType></xs:element><xs:element name="FullCountryInfoAllCountriesResponse"><xs:complexType><xs:sequence><xs:element name="FullCountryInfoAllCountriesResult" type="tns:ArrayOftCountryInfo"/></xs:sequence></xs:complexType></xs:element><xs:element name="CountriesUsingCurrency"><xs:complexType><xs:sequence><xs:element name="sISOCurrencyCode" type="xs:string"/></xs:sequence></xs:complexType></xs:element><xs:element name="CountriesUsingCurrencyResponse"><xs:complexType><xs:sequence><xs:element name="CountriesUsingCurrencyResult" type="tns:ArrayOftCountryCodeAndName"/></xs:sequence></xs:complexType></xs:element><xs:element name="ListOfLanguagesByName"><xs:complexType><xs:sequence/></xs:complexType></xs:element><xs:element name="ListOfLanguagesByNameResponse"><xs:complexType><xs:sequence><xs:element name="ListOfLanguagesByNameResult" type="tns:ArrayOftLanguage"/></xs:sequence></xs:complexType></xs:element><xs:element name="ListOfLanguagesByCode"><xs:complexType><xs:sequence/></xs:complexType></xs:element><xs:element name="ListOfLanguagesByCodeResponse"><xs:complexType><xs:sequence><xs:element name="ListOfLanguagesByCodeResult" type="tns:ArrayOftLanguage"/></xs:sequence></xs:complexType></xs:element><xs:element name="LanguageName"><xs:complexType><xs:sequence><xs:element name="sISOCode" type="xs:string"/></xs:sequence></xs:complexType></xs:element><xs:element name="LanguageNameResponse"><xs:complexType><xs:sequence><xs:element name="LanguageNameResult" type="xs:string"/></xs:sequence></xs:complexType></xs:element><xs:element name="LanguageISOCode"><xs:complexType><xs:sequence><xs:element name="sLanguageName" type="xs:string"/></xs:sequence></xs:complexType></xs:element><xs:element name="LanguageISOCodeResponse"><xs:complexType><xs:sequence><xs:element name="LanguageISOCodeResult" type="xs:string"/></xs:sequence></xs:complexType></xs:element></xs:schema></types><message name="ListOfContinentsByNameSoapRequest"><part name="parameters" element="tns:ListOfContinentsByName"/></message><message name="ListOfContinentsByNameSoapResponse"><part name="parameters" element="tns:ListOfContinentsByNameResponse"/></message><message name="ListOfContinentsByCodeSoapRequest"><part name="parameters" element="tns:ListOfContinentsByCode"/></message><message name="ListOfContinentsByCodeSoapResponse"><part name="parameters" element="tns:ListOfContinentsByCodeResponse"/></message><message name="ListOfCurrenciesByNameSoapRequest"><part name="parameters" element="tns:ListOfCurrenciesByName"/></message><message name="ListOfCurrenciesByNameSoapResponse"><part name="parameters" element="tns:ListOfCurrenciesByNameResponse"/></message><message name="ListOfCurrenciesByCodeSoapRequest"><part name="parameters" element="tns:ListOfCurrenciesByCode"/></message><message name="ListOfCurrenciesByCodeSoapResponse"><part name="parameters" element="tns:ListOfCurrenciesByCodeResponse"/></message><message name="CurrencyNameSoapRequest"><part name="parameters" element="tns:CurrencyName"/></message><message name="CurrencyNameSoapResponse"><part name="parameters" element="tns:CurrencyNameResponse"/></message><message name="ListOfCountryNamesByCodeSoapRequest"><part name="parameters" element="tns:ListOfCountryNamesByCode"/></message><message name="ListOfCountryNamesByCodeSoapResponse"><part name="parameters" element="tns:ListOfCountryNamesByCodeResponse"/></message><message name="ListOfCountryNamesByNameSoapRequest"><part name="parameters" element="tns:ListOfCountryNamesByName"/></message><message name="ListOfCountryNamesByNameSoapResponse"><part name="parameters" element="tns:ListOfCountryNamesByNameResponse"/></message><message name="ListOfCountryNamesGroupedByContinentSoapRequest"><part name="parameters" element="tns:ListOfCountryNamesGroupedByContinent"/></message><message name="ListOfCountryNamesGroupedByContinentSoapResponse"><part name="parameters" element="tns:ListOfCountryNamesGroupedByContinentResponse"/></message><message name="CountryNameSoapRequest"><part name="parameters" element="tns:CountryName"/></message><message name="CountryNameSoapResponse"><part name="parameters" element="tns:CountryNameResponse"/></message><message name="CountryISOCodeSoapRequest"><part name="parameters" element="tns:CountryISOCode"/></message><message name="CountryISOCodeSoapResponse"><part name="parameters" element="tns:CountryISOCodeResponse"/></message><message name="CapitalCitySoapRequest"><part name="parameters" element="tns:CapitalCity"/></message><message name="CapitalCitySoapResponse"><part name="parameters" element="tns:CapitalCityResponse"/></message><message name="CountryCurrencySoapRequest"><part name="parameters" element="tns:CountryCurrency"/></message><message name="CountryCurrencySoapResponse"><part name="parameters" element="tns:CountryCurrencyResponse"/></message><message name="CountryFlagSoapRequest"><part name="parameters" element="tns:CountryFlag"/></message><message name="CountryFlagSoapResponse"><part name="parameters" element="tns:CountryFlagResponse"/></message><message name="CountryIntPhoneCodeSoapRequest"><part name="parameters" element="tns:CountryIntPhoneCode"/></message><message name="CountryIntPhoneCodeSoapResponse"><part name="parameters" element="tns:CountryIntPhoneCodeResponse"/></message><message name="FullCountryInfoSoapRequest"><part name="parameters" element="tns:FullCountryInfo"/></message><message name="FullCountryInfoSoapResponse"><part name="parameters" element="tns:FullCountryInfoResponse"/></message><message name="FullCountryInfoAllCountriesSoapRequest"><part name="parameters" element="tns:FullCountryInfoAllCountries"/></message><message name="FullCountryInfoAllCountriesSoapResponse"><part name="parameters" element="tns:FullCountryInfoAllCountriesResponse"/></message><message name="CountriesUsingCurrencySoapRequest"><part name="parameters" element="tns:CountriesUsingCurrency"/></message><message name="CountriesUsingCurrencySoapResponse"><part name="parameters" element="tns:CountriesUsingCurrencyResponse"/></message><message name="ListOfLanguagesByNameSoapRequest"><part name="parameters" element="tns:ListOfLanguagesByName"/></message><message name="ListOfLanguagesByNameSoapResponse"><part name="parameters" element="tns:ListOfLanguagesByNameResponse"/></message><message name="ListOfLanguagesByCodeSoapRequest"><part name="parameters" element="tns:ListOfLanguagesByCode"/></message><message name="ListOfLanguagesByCodeSoapResponse"><part name="parameters" element="tns:ListOfLanguagesByCodeResponse"/></message><message name="LanguageNameSoapRequest"><part name="parameters" element="tns:LanguageName"/></message><message name="LanguageNameSoapResponse"><part name="parameters" element="tns:LanguageNameResponse"/></message><message name="LanguageISOCodeSoapRequest"><part name="parameters" element="tns:LanguageISOCode"/></message><message name="LanguageISOCodeSoapResponse"><part name="parameters" element="tns:LanguageISOCodeResponse"/></message><portType name="CountryInfoServiceSoapType"><operation name="ListOfContinentsByName"><documentation>Returns a list of continents ordered by name.</documentation><input message="tns:ListOfContinentsByNameSoapRequest"/><output message="tns:ListOfContinentsByNameSoapResponse"/></operation><operation name="ListOfContinentsByCode"><documentation>Returns a list of continents ordered by code.</documentation><input message="tns:ListOfContinentsByCodeSoapRequest"/><output message="tns:ListOfContinentsByCodeSoapResponse"/></operation><operation name="ListOfCurrenciesByName"><documentation>Returns a list of currencies ordered by name.</documentation><input message="tns:ListOfCurrenciesByNameSoapRequest"/><output message="tns:ListOfCurrenciesByNameSoapResponse"/></operation><operation name="ListOfCurrenciesByCode"><documentation>Returns a list of currencies ordered by code.</documentation><input message="tns:ListOfCurrenciesByCodeSoapRequest"/><output message="tns:ListOfCurrenciesByCodeSoapResponse"/></operation><operation name="CurrencyName"><documentation>Returns the name of the currency (if found)</documentation><input message="tns:CurrencyNameSoapRequest"/><output message="tns:CurrencyNameSoapResponse"/></operation><operation name="ListOfCountryNamesByCode"><documentation>Returns a list of all stored counties ordered by ISO code</documentation><input message="tns:ListOfCountryNamesByCodeSoapRequest"/><output message="tns:ListOfCountryNamesByCodeSoapResponse"/></operation><operation name="ListOfCountryNamesByName"><documentation>Returns a list of all stored counties ordered by country name</documentation><input message="tns:ListOfCountryNamesByNameSoapRequest"/><output message="tns:ListOfCountryNamesByNameSoapResponse"/></operation><operation name="ListOfCountryNamesGroupedByContinent"><documentation>Returns a list of all stored counties grouped per continent</documentation><input message="tns:ListOfCountryNamesGroupedByContinentSoapRequest"/><output message="tns:ListOfCountryNamesGroupedByContinentSoapResponse"/></operation><operation name="CountryName"><documentation>Searches the database for a country by the passed ISO country code</documentation><input message="tns:CountryNameSoapRequest"/><output message="tns:CountryNameSoapResponse"/></operation><operation name="CountryISOCode"><documentation>This function tries to found a country based on the passed country name.</documentation><input message="tns:CountryISOCodeSoapRequest"/><output message="tns:CountryISOCodeSoapResponse"/></operation><operation name="CapitalCity"><documentation>Returns the  name of the captial city for the passed country code</documentation><input message="tns:CapitalCitySoapRequest"/><output message="tns:CapitalCitySoapResponse"/></operation><operation name="CountryCurrency"><documentation>Returns the currency ISO code and name for the passed country ISO code</documentation><input message="tns:CountryCurrencySoapRequest"/><output message="tns:CountryCurrencySoapResponse"/></operation><operation name="CountryFlag"><documentation>Returns a link to a picture of the country flag</documentation><input message="tns:CountryFlagSoapRequest"/><output message="tns:CountryFlagSoapResponse"/></operation><operation name="CountryIntPhoneCode"><documentation>Returns the internation phone code for the passed ISO country code</documentation><input message="tns:CountryIntPhoneCodeSoapRequest"/><output message="tns:CountryIntPhoneCodeSoapResponse"/></operation><operation name="FullCountryInfo"><documentation>Returns a struct with all the stored country information. Pass the ISO country code</documentation><input message="tns:FullCountryInfoSoapRequest"/><output message="tns:FullCountryInfoSoapResponse"/></operation><operation name="FullCountryInfoAllCountries"><documentation>Returns an array with all countries and all the language information stored</documentation><input message="tns:FullCountryInfoAllCountriesSoapRequest"/><output message="tns:FullCountryInfoAllCountriesSoapResponse"/></operation><operation name="CountriesUsingCurrency"><documentation>Returns a list of all countries that use the same currency code. Pass a ISO currency code</documentation><input message="tns:CountriesUsingCurrencySoapRequest"/><output message="tns:CountriesUsingCurrencySoapResponse"/></operation><operation name="ListOfLanguagesByName"><documentation>Returns an array of languages ordered by name</documentation><input message="tns:ListOfLanguagesByNameSoapRequest"/><output message="tns:ListOfLanguagesByNameSoapResponse"/></operation><operation name="ListOfLanguagesByCode"><documentation>Returns an array of languages ordered by code</documentation><input message="tns:ListOfLanguagesByCodeSoapRequest"/><output message="tns:ListOfLanguagesByCodeSoapResponse"/></operation><operation name="LanguageName"><documentation>Find a language name based on the passed ISO language code</documentation><input message="tns:LanguageNameSoapRequest"/><output message="tns:LanguageNameSoapResponse"/></operation><operation name="LanguageISOCode"><documentation>Find a language ISO code based on the passed language name</documentation><input message="tns:LanguageISOCodeSoapRequest"/><output message="tns:LanguageISOCodeSoapResponse"/></operation></portType><binding name="CountryInfoServiceSoapBinding" type="tns:CountryInfoServiceSoapType"><soap:binding style="document" transport="http://schemas.xmlsoap.org/soap/http"/><operation name="ListOfContinentsByName"><soap:operation soapAction="" style="document"/><input><soap:body use="literal"/></input><output><soap:body use="literal"/></output></operation><operation name="ListOfContinentsByCode"><soap:operation soapAction="" style="document"/><input><soap:body use="literal"/></input><output><soap:body use="literal"/></output></operation><operation name="ListOfCurrenciesByName"><soap:operation soapAction="" style="document"/><input><soap:body use="literal"/></input><output><soap:body use="literal"/></output></operation><operation name="ListOfCurrenciesByCode"><soap:operation soapAction="" style="document"/><input><soap:body use="literal"/></input><output><soap:body use="literal"/></output></operation><operation name="CurrencyName"><soap:operation soapAction="" style="document"/><input><soap:body use="literal"/></input><output><soap:body use="literal"/></output></operation><operation name="ListOfCountryNamesByCode"><soap:operation soapAction="" style="document"/><input><soap:body use="literal"/></input><output><soap:body use="literal"/></output></operation><operation name="ListOfCountryNamesByName"><soap:operation soapAction="" style="document"/><input><soap:body use="literal"/></input><output><soap:body use="literal"/></output></operation><operation name="ListOfCountryNamesGroupedByContinent"><soap:operation soapAction="" style="document"/><input><soap:body use="literal"/></input><output><soap:body use="literal"/></output></operation><operation name="CountryName"><soap:operation soapAction="" style="document"/><input><soap:body use="literal"/></input><output><soap:body use="literal"/></output></operation><operation name="CountryISOCode"><soap:operation soapAction="" style="document"/><input><soap:body use="literal"/></input><output><soap:body use="literal"/></output></operation><operation name="CapitalCity"><soap:operation soapAction="" style="document"/><input><soap:body use="literal"/></input><output><soap:body use="literal"/></output></operation><operation name="CountryCurrency"><soap:operation soapAction="" style="document"/><input><soap:body use="literal"/></input><output><soap:body use="literal"/></output></operation><operation name="CountryFlag"><soap:operation soapAction="" style="document"/><input><soap:body use="literal"/></input><output><soap:body use="literal"/></output></operation><operation name="CountryIntPhoneCode"><soap:operation soapAction="" style="document"/><input><soap:body use="literal"/></input><output><soap:body use="literal"/></output></operation><operation name="FullCountryInfo"><soap:operation soapAction="" style="document"/><input><soap:body use="literal"/></input><output><soap:body use="literal"/></output></operation><operation name="FullCountryInfoAllCountries"><soap:operation soapAction="" style="document"/><input><soap:body use="literal"/></input><output><soap:body use="literal"/></output></operation><operation name="CountriesUsingCurrency"><soap:operation soapAction="" style="document"/><input><soap:body use="literal"/></input><output><soap:body use="literal"/></output></operation><operation name="ListOfLanguagesByName"><soap:operation soapAction="" style="document"/><input><soap:body use="literal"/></input><output><soap:body use="literal"/></output></operation><operation name="ListOfLanguagesByCode"><soap:operation soapAction="" style="document"/><input><soap:body use="literal"/></input><output><soap:body use="literal"/></output></operation><operation name="LanguageName"><soap:operation soapAction="" style="document"/><input><soap:body use="literal"/></input><output><soap:body use="literal"/></output></operation><operation name="LanguageISOCode"><soap:operation soapAction="" style="document"/><input><soap:body use="literal"/></input><output><soap:body use="literal"/></output></operation></binding><binding name="CountryInfoServiceSoapBinding12" type="tns:CountryInfoServiceSoapType"><soap12:binding style="document" transport="http://schemas.xmlsoap.org/soap/http"/><operation name="ListOfContinentsByName"><soap12:operation soapAction="" style="document"/><input><soap12:body use="literal"/></input><output><soap12:body use="literal"/></output></operation><operation name="ListOfContinentsByCode"><soap12:operation soapAction="" style="document"/><input><soap12:body use="literal"/></input><output><soap12:body use="literal"/></output></operation><operation name="ListOfCurrenciesByName"><soap12:operation soapAction="" style="document"/><input><soap12:body use="literal"/></input><output><soap12:body use="literal"/></output></operation><operation name="ListOfCurrenciesByCode"><soap12:operation soapAction="" style="document"/><input><soap12:body use="literal"/></input><output><soap12:body use="literal"/></output></operation><operation name="CurrencyName"><soap12:operation soapAction="" style="document"/><input><soap12:body use="literal"/></input><output><soap12:body use="literal"/></output></operation><operation name="ListOfCountryNamesByCode"><soap12:operation soapAction="" style="document"/><input><soap12:body use="literal"/></input><output><soap12:body use="literal"/></output></operation><operation name="ListOfCountryNamesByName"><soap12:operation soapAction="" style="document"/><input><soap12:body use="literal"/></input><output><soap12:body use="literal"/></output></operation><operation name="ListOfCountryNamesGroupedByContinent"><soap12:operation soapAction="" style="document"/><input><soap12:body use="literal"/></input><output><soap12:body use="literal"/></output></operation><operation name="CountryName"><soap12:operation soapAction="" style="document"/><input><soap12:body use="literal"/></input><output><soap12:body use="literal"/></output></operation><operation name="CountryISOCode"><soap12:operation soapAction="" style="document"/><input><soap12:body use="literal"/></input><output><soap12:body use="literal"/></output></operation><operation name="CapitalCity"><soap12:operation soapAction="" style="document"/><input><soap12:body use="literal"/></input><output><soap12:body use="literal"/></output></operation><operation name="CountryCurrency"><soap12:operation soapAction="" style="document"/><input><soap12:body use="literal"/></input><output><soap12:body use="literal"/></output></operation><operation name="CountryFlag"><soap12:operation soapAction="" style="document"/><input><soap12:body use="literal"/></input><output><soap12:body use="literal"/></output></operation><operation name="CountryIntPhoneCode"><soap12:operation soapAction="" style="document"/><input><soap12:body use="literal"/></input><output><soap12:body use="literal"/></output></operation><operation name="FullCountryInfo"><soap12:operation soapAction="" style="document"/><input><soap12:body use="literal"/></input><output><soap12:body use="literal"/></output></operation><operation name="FullCountryInfoAllCountries"><soap12:operation soapAction="" style="document"/><input><soap12:body use="literal"/></input><output><soap12:body use="literal"/></output></operation><operation name="CountriesUsingCurrency"><soap12:operation soapAction="" style="document"/><input><soap12:body use="literal"/></input><output><soap12:body use="literal"/></output></operation><operation name="ListOfLanguagesByName"><soap12:operation soapAction="" style="document"/><input><soap12:body use="literal"/></input><output><soap12:body use="literal"/></output></operation><operation name="ListOfLanguagesByCode"><soap12:operation soapAction="" style="document"/><input><soap12:body use="literal"/></input><output><soap12:body use="literal"/></output></operation><operation name="LanguageName"><soap12:operation soapAction="" style="document"/><input><soap12:body use="literal"/></input><output><soap12:body use="literal"/></output></operation><operation name="LanguageISOCode"><soap12:operation soapAction="" style="document"/><input><soap12:body use="literal"/></input><output><soap12:body use="literal"/></output></operation></binding><service name="CountryInfoService"><documentation>This DataFlex Web Service opens up country information. 2 letter ISO codes are used for Country code. There are functions to retrieve the used Currency, Language, Capital City, Continent and Telephone code.</documentation><port name="CountryInfoServiceSoap" binding="tns:CountryInfoServiceSoapBinding"><soap:address location="http://webservices.oorsprong.org/websamples.countryinfo/CountryInfoService.wso"/></port><port name="CountryInfoServiceSoap12" binding="tns:CountryInfoServiceSoapBinding12"><soap12:address location="http://webservices.oorsprong.org/websamples.countryinfo/CountryInfoService.wso"/></port></service></definitions>"""


@pytest.fixture
def xml_response():
    return """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <ListOfLanguagesByCodeResponse xmlns="http://www.oorsprong.org/websamples.countryinfo">
      <ListOfLanguagesByCodeResult>
        <tLanguage>
          <sISOCode>FR</sISOCode>
          <sName>French</sName>
        </tLanguage>
        <tLanguage>
          <sISOCode>US</sISOCode>
          <sName>English</sName>
        </tLanguage>
      </ListOfLanguagesByCodeResult>
    </ListOfLanguagesByCodeResponse>
  </soap:Body>
</soap:Envelope>"""
