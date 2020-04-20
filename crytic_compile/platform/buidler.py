"""
Truffle platform
"""
import glob
import json
import logging
import os
import platform
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Tuple, List, Dict

from crytic_compile.platform.types import Type
from crytic_compile.platform.exceptions import InvalidCompilation
from crytic_compile.utils.naming import convert_filename, extract_name, extract_filename
from crytic_compile.compiler.compiler import CompilerVersion
from crytic_compile.platform import solc
from crytic_compile.utils.natspec import Natspec
from .abstract_platform import AbstractPlatform

# Handle cycle
from .solc import relative_to_short

if TYPE_CHECKING:
    from crytic_compile import CryticCompile

LOGGER = logging.getLogger("CryticCompile")


class Buidler(AbstractPlatform):
    """
    Builder platform
    """

    NAME = "Buidler"
    PROJECT_URL = "https://github.com/nomiclabs/buidler"
    TYPE = Type.BUILDER

    def compile(self, crytic_compile: "CryticCompile", **kwargs: str):
        """
        Compile the target

        :param kwargs:
        :return:
        """

        cache_directory = kwargs.get("buidler_cache_directory")
        target_file = os.path.join(cache_directory, "solc-output.json")
        buidler_ignore_compile = kwargs.get("buidler_ignore_compile", False) or kwargs.get(
            "buidler_compile", False
        )
        buidler_working_dir = kwargs.get("buidler_working_dir", None)

        base_cmd = ["buidler"]
        if not kwargs.get("npx_disable", False):
            base_cmd = ["npx"] + base_cmd

        if not buidler_ignore_compile:
            cmd = base_cmd + ["compile"]

            LOGGER.info(
                "'%s' running",
                " ".join(cmd),
            )

            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self._target
            )

            stdout_bytes, stderr_bytes = process.communicate()
            stdout, stderr = (
                stdout_bytes.decode(),
                stderr_bytes.decode(),
            )  # convert bytestrings to unicode strings

            LOGGER.info(stdout)
            if stderr:
                LOGGER.error(stderr)

        if not os.path.isfile(os.path.join(self._target, target_file)):
            raise InvalidCompilation("`buidler compile` failed. Can you run it?")

        # TODO: find a better way to get this information
        compiler = "solc"

        (version_from_config, optimized) = _get_version_from_config(cache_directory)

        crytic_compile.compiler_version = CompilerVersion(
            compiler=compiler, version=version_from_config, optimized=optimized
        )

        skip_filename = crytic_compile.compiler_version.version in [
            f"0.4.{x}" for x in range(0, 10)
        ]

        with open(target_file, encoding="utf8") as file_desc:
            targets_json = json.load(file_desc)

            if "contracts" in targets_json:
                for original_filename, contracts_info in targets_json["contracts"].items():
                    for original_contract_name, info in contracts_info.items():
                        contract_name = extract_name(original_contract_name)

                        contract_filename = convert_filename(
                            original_filename,
                            relative_to_short,
                            crytic_compile,
                            working_dir=buidler_working_dir,
                        )

                        crytic_compile.contracts_names.add(contract_name)
                        crytic_compile.contracts_filenames[contract_name] = contract_filename

                        crytic_compile.abis[contract_name] = info["abi"]
                        crytic_compile.bytecodes_init[contract_name] = info["evm"]["bytecode"]["object"]
                        crytic_compile.bytecodes_runtime[contract_name] = info["evm"]["deployedBytecode"]["object"]
                        crytic_compile.srcmaps_init[contract_name] = info["evm"]["bytecode"]["sourceMap"].split(";")
                        crytic_compile.srcmaps_runtime[contract_name] = info["evm"]["bytecode"]["sourceMap"].split(";")
                        userdoc = json.loads(info.get("userdoc", "{}"))
                        devdoc = json.loads(info.get("devdoc", "{}"))
                        natspec = Natspec(userdoc, devdoc)
                        crytic_compile.natspec[contract_name] = natspec

            if "sources" in targets_json:
                for path, info in targets_json["sources"].items():
                    if skip_filename:
                        path = convert_filename(
                            self._target,
                            relative_to_short,
                            crytic_compile,
                            working_dir=buidler_working_dir,
                        )
                    else:
                        path = convert_filename(
                            path, relative_to_short, crytic_compile, working_dir=buidler_working_dir
                        )
                    crytic_compile.filenames.add(path)
                    crytic_compile.asts[path.absolute] = info["ast"]



    @staticmethod
    def is_supported(target: str, **kwargs: str) -> bool:
        """
        Check if the target is a truffle project

        :param target:
        :return:
        """
        buidler_ignore = kwargs.get("buidler_ignore", False)
        if buidler_ignore:
            return False
        return os.path.isfile(os.path.join(target, "buidler.config.js"))

    def is_dependency(self, path: str) -> bool:
        """
        Check if the target is a dependency

        :param path:
        :return:
        """
        return "node_modules" in Path(path).parts

    def _guessed_tests(self) -> List[str]:
        """
        Guess the potential unit tests commands

        :return:
        """
        return ["truffle test"]


def _get_version_from_config(builder_directory: Path) -> Optional[Tuple[str, str]]:
    """
    :return: (version, optimized)
    """
    config = Path(builder_directory, "last-solc-config.json")
    if not config.exists():
        raise InvalidCompilation(f"{config} not found")
    with open(config) as config_f:
        config = json.load(config_f)

    version = config['solc']['version']

    optimized = 'optimizer' in config['solc'] and config['solc']['optimizer']
    return version, optimized
