Installation
============

Requirements
------------

* **Python**: 3.11 or higher
* **SQLAlchemy**: 2.0 or higher (for ORM integration)
* **boto3**: 1.34 or higher (required for S3 backend)

Package Installation
--------------------

**Using pip**:

.. code-block:: bash

   pip install granite-storage

**Using UV** (fastest):

.. code-block:: bash

   uv add granite-storage

**Using Poetry**:

.. code-block:: bash

   poetry add granite-storage

Development Installation
------------------------

.. code-block:: bash

   git clone https://github.com/impalah/granite-storage.git
   cd granite-storage
   uv sync

Optional Extras
---------------

No additional extras are required. ``boto3`` is declared as a hard dependency to ensure
S3 functionality is always available. If you only need local storage in a constrained
environment you can install without it and stub the import — see :doc:`implementing-backend`.
