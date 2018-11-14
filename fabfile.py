import os
from invoke import task

from fabric import Connection
import jinja2


def _get_var(key):
    if key not in os.environ:
        raise Exception("Missing environment variable %r" % key)
    return os.environ[key]


CONSTANTS = {
    "venv": "/envs/captionary",
    "OAUTH_TOKEN": _get_var("OAUTH_TOKEN"),
    "conf": "/etc/emperor/captionary.ini",
}


def _render(filename, **context):
    with open(filename, "r") as ifile:
        tmpl = jinja2.Template(ifile.read())
    basename = os.path.basename(filename)
    if not os.path.isdir("dist"):
        os.makedirs("dist")
    outfile = os.path.join("dist", basename)
    with open(outfile, "w") as ofile:
        ofile.write(tmpl.render(**context))
    return outfile


def _render_put(c, filename, dest, **kwargs):
    rendered = _render(filename, **CONSTANTS)
    c.put(rendered, dest, **kwargs)


@task
def build(c):
    version = c.run("git describe --tags").stdout.strip()
    c.run("sed -i -e 's/version=.*/version=\"%s\",/' setup.py" % version)
    c.run("python setup.py sdist")
    c.run("sed -i -e 's/version=.*/version=\"develop\",/' setup.py")
    _render("prod.ini.tmpl", **CONSTANTS)
    print("Created dist/captionary-%s.tar.gz" % version)
    return version


@task
def deploy(c):
    do_deploy(c, Connection("stevearc.com", "stevearc"))


def do_deploy(local, remote):
    version = build(local)
    tarball = "captionary-%s.tar.gz" % version
    remote.put("dist/" + tarball)
    remote.run("if [ ! -e {0} ]; then true; fi".format(CONSTANTS["venv"]))
    resp = remote.run("ls " + CONSTANTS["venv"], warn=True, hide=True)
    if resp.exited:
        remote.sudo("virtualenv " + CONSTANTS["venv"])
    pip = os.path.join(CONSTANTS["venv"], "bin", "pip")
    remote.sudo(pip + " uninstall -y captionary", warn=True, hide=True)
    remote.sudo(pip + " install pastescript")
    remote.sudo(pip + " install %s" % tarball)
    _render_put(remote, "prod.ini.tmpl", "captionary.ini")
    remote.sudo("rm -f captionary")
    _render_put(remote, "cron.tmpl", "captionary")
    remote.sudo("chmod 644 captionary")
    remote.sudo("chown root:root captionary")
    remote.sudo("mv captionary /etc/cron.d")
    remote.sudo("mv captionary.ini %s" % CONSTANTS["conf"])
