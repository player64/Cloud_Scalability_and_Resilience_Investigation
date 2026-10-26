PROFILE ?=

TF = terraform -chdir=infra
TF_VARS = -var-file=secrets.tfvars -var-file=common.tfvars -var-file=$(PROFILE).tfvars

.PHONY: check-profile plan apply destroy

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

destroy: check-profile
	$(TF) destroy $(TF_VARS)
	@rm -f infra/outputs.json
