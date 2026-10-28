PROFILE ?=
SSH_KEY_PATH ?= $(HOME)/.ssh/mj256.pem

TF = terraform -chdir=infra
TF_VARS = -var-file=secrets.tfvars -var-file=common.tfvars -var-file=$(PROFILE).tfvars
SSH_KEY_OPTION = $(if $(SSH_KEY_PATH),-i "$(SSH_KEY_PATH)",)
SSH_OPTIONS = $(SSH_KEY_OPTION) -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new

.PHONY: check-profile plan apply copy-outputs sync destroy

check-profile:
	@case "$(PROFILE)" in baseline|scaled|elasticity|failure) ;; \
		*) printf 'Set PROFILE to baseline, scaled, elasticity or failure.\n' >&2; exit 1 ;; \
	esac

plan: check-profile
	$(TF) plan $(TF_VARS)

apply: check-profile
	@rm -f infra/outputs.json
	$(TF) apply $(TF_VARS)
	@umask 077; trap 'rm -f infra/outputs.json.tmp' EXIT; \
		$(TF) output -json > infra/outputs.json.tmp && \
		mv infra/outputs.json.tmp infra/outputs.json
	@$(MAKE) copy-outputs

copy-outputs:
	@test -s infra/outputs.json || { printf 'Missing infra/outputs.json; apply first.\n' >&2; exit 1; }
	@set -eu; host=$$($(TF) output -raw load_generator_public_ip); \
		attempt=0; \
		until ssh $(SSH_OPTIONS) "ubuntu@$$host" true 2>/dev/null; do \
			attempt=$$((attempt + 1)); \
			if [ "$$attempt" -ge 12 ]; then printf 'SSH to the load generator failed; infrastructure may already be applied. Retry with make copy-outputs.\n' >&2; exit 1; fi; \
			sleep 5; \
		done; \
		ssh $(SSH_OPTIONS) "ubuntu@$$host" 'timeout 900 cloud-init status --wait >/dev/null'; \
		scp $(SSH_OPTIONS) infra/outputs.json "ubuntu@$$host:ca1/infra/outputs.json"; \
		ssh $(SSH_OPTIONS) "ubuntu@$$host" 'chmod 600 ~/ca1/infra/outputs.json'

sync:
	@set -eu; bucket=$$($(TF) output -raw evidence_bucket); \
		region=$$($(TF) output -raw aws_region); \
		mkdir -p evidence; \
		aws s3 sync "s3://$$bucket/evidence/" evidence/ --region "$$region" --only-show-errors

destroy: check-profile
	$(TF) destroy $(TF_VARS)
	@rm -f infra/outputs.json
