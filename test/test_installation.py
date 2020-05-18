import subprocess


def test_install_pyan3():
    MyOut = subprocess.Popen(['pip', 'install', '.'],
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
    stdout, stderr = MyOut.communicate()
    assert stderr == None, stderr.decode()
    assert "Successfully installed pyan3" in stdout.decode(), stdout.decode()


def test_no_parameter():
    MyOut = subprocess.Popen(['pyan3'],
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
    stdout, stderr = MyOut.communicate()
    assert stderr == None, stderr.decode()
    assert "Need one or more filenames to process" in stdout.decode()


def test_double_dash_help():
    MyOut = subprocess.Popen(['pyan3', '--help'],
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
    stdout, stderr = MyOut.communicate()
    assert stderr == None, stderr.decode()
    assert "-h, --help            show this help message and exit" in stdout.decode()


def test_single_dash_help():
    MyOut = subprocess.Popen(['pyan3', '-h'],
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
    stdout, stderr = MyOut.communicate()
    assert stderr == None, stderr.decode()
    assert "-h, --help            show this help message and exit" in stdout.decode()


def test_visualize_architecture():
    MyOut = subprocess.Popen(['./visualize_pyan_architecture.sh'],
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
    stdout, stderr = MyOut.communicate()
    assert stderr == None, stderr.decode()
    assert "Pyan architecture: generating architecture" in stdout.decode()
